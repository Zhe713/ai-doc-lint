"""版本 diff 比对与放行 API（P3-1）。

- 从 Artifact(plaintext) 取两份文档正文，difflib 行级对比（实现只在 diff_texts 一处）；
- 返回逐行 type（equal/add/del）+ 统计（相同/新增/删除行数）+ identical；
- 放行（release）落库到 document_releases，并在服务端重新校验「确实无差异」，
  避免开关再次退化成界面上的一个徽标。
"""

import difflib

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db import storage
from app.db.session import get_db
from app.models.document import (
    ART_PLAINTEXT,
    RELEASE_DIFF_AUTO,
    RELEASE_KINDS,
    RELEASE_MANUAL,
    Artifact,
    Document,
    DocumentRelease,
)
from app.models.user import User

router = APIRouter(tags=["compare"])

_MAX_DIFF_CHARS = 60_000  # 单侧文本上限，超出截断并标记 truncated


def diff_texts(text_a: str, text_b: str, auto_bypass: bool = False) -> dict:
    """纯函数：两份文本的行级 diff + 统计（供测试与 API 复用）。"""
    truncated = False
    if len(text_a) > _MAX_DIFF_CHARS or len(text_b) > _MAX_DIFF_CHARS:
        truncated = True
        text_a = text_a[:_MAX_DIFF_CHARS]
        text_b = text_b[:_MAX_DIFF_CHARS]

    lines_a = text_a.splitlines()
    lines_b = text_b.splitlines()
    sm = difflib.SequenceMatcher(a=lines_a, b=lines_b, autojunk=False)
    ops = sm.get_opcodes()

    rows: list[dict] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for k in range(i1, i2):
                rows.append({"type": "equal", "text": lines_a[k], "line_a": k + 1, "line_b": k + 1})
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append({"type": "del", "text": lines_a[k], "line_a": k + 1, "line_b": None})
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append({"type": "add", "text": lines_b[k], "line_a": None, "line_b": k + 1})
        else:  # replace
            for k in range(i1, i2):
                rows.append({"type": "del", "text": lines_a[k], "line_a": k + 1, "line_b": None})
            for k in range(j1, j2):
                rows.append({"type": "add", "text": lines_b[k], "line_a": None, "line_b": k + 1})

    add_lines = sum(1 for r in rows if r["type"] == "add")
    del_lines = sum(1 for r in rows if r["type"] == "del")
    same_lines = sum(1 for r in rows if r["type"] == "equal")
    identical = add_lines == 0 and del_lines == 0

    return {
        "identical": identical,
        "auto_bypass": auto_bypass,
        "bypass_ready": identical and auto_bypass,
        "stats": {"same_lines": same_lines, "add_lines": add_lines,
                  "del_lines": del_lines, "changed_ratio": round(
                      (add_lines + del_lines) / max(same_lines + add_lines + del_lines, 1), 4)},
        "truncated": truncated,
        "rows": rows,
    }


def _get_plaintext(db: Session, doc_id: str) -> tuple[str, str]:
    doc = db.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    art = (
        db.query(Artifact)
        .filter(Artifact.document_id == doc.id, Artifact.kind == ART_PLAINTEXT)
        .order_by(Artifact.created_at.desc())
        .first()
    )
    if art is None:
        raise HTTPException(status_code=409, detail=f"文档 {doc.filename} 尚未解析出文本")
    text = storage.get_object_bytes(art.storage_key).decode("utf-8", errors="replace")
    return doc.filename, text


@router.get("/compare/diff")
def document_diff(
    doc_a_id: str,
    doc_b_id: str,
    auto_bypass: bool = False,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    if doc_a_id == doc_b_id:
        raise HTTPException(status_code=422, detail="请选择两份不同的文档进行比对")

    fn_a, text_a = _get_plaintext(db, doc_a_id)
    fn_b, text_b = _get_plaintext(db, doc_b_id)

    # 单一实现：差异计算只在 diff_texts 里写一次（此前这里是复制体，两边会漂移）
    result = diff_texts(text_a, text_b, auto_bypass=auto_bypass)
    return {
        "doc_a": {"id": doc_a_id, "filename": fn_a, "chars": len(text_a)},
        "doc_b": {"id": doc_b_id, "filename": fn_b, "chars": len(text_b)},
        **result,
    }


class ReleaseIn(BaseModel):
    """放行请求：把「无差异可放行」从徽标变成一条可查询的事实。"""

    document_id: str
    baseline_document_id: str | None = None
    note: str | None = Field(default=None, max_length=255)
    kind: str = RELEASE_DIFF_AUTO


@router.post("/compare/release")
def release_after_diff(
    body: ReleaseIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """版本对比后放行：仅当与基线版本确实无差异时才允许自动放行。

    服务端重新算一次差异，不信任前端传来的 identical —— 否则这个开关又变成
    「界面说了算」。差异非空时返回 409，并给出变更比例，让用户先人工确认。
    """
    from app.services.coverage import release_out

    doc_b_id = body.document_id
    if not doc_b_id:
        raise HTTPException(status_code=422, detail="缺少要放行的文档")
    doc = db.get(Document, doc_b_id)
    if doc is None or doc.user_id != current.id:
        raise HTTPException(status_code=404, detail="文档不存在")

    baseline_id = body.baseline_document_id
    if not baseline_id or baseline_id == doc_b_id:
        raise HTTPException(status_code=422, detail="请选择用于对照的基线版本")

    _, text_a = _get_plaintext(db, baseline_id)
    _, text_b = _get_plaintext(db, doc_b_id)
    result = diff_texts(text_a, text_b, auto_bypass=True)

    if body.kind == RELEASE_DIFF_AUTO and not result["identical"]:
        raise HTTPException(
            status_code=409,
            detail=f"与基线版本存在差异（变更比例 {result['stats']['changed_ratio']:.2%}），"
                   "不能自动放行，请人工确认后手动放行",
        )

    row = DocumentRelease(
        document_id=doc.id,
        user_id=current.id,
        kind=body.kind if body.kind in RELEASE_KINDS else RELEASE_MANUAL,
        baseline_document_id=baseline_id,
        changed_ratio=result["stats"]["changed_ratio"],
        note=body.note,
    )
    db.add(row)
    from app.services.audit_service import write_audit

    write_audit(db, action="document_release", user_id=current.id,
                username=current.username, target=doc.filename,
                detail={"kind": row.kind, "baseline": str(baseline_id),
                        "changed_ratio": row.changed_ratio})
    db.commit()
    db.refresh(row)
    return {"ok": True, "released": release_out(row).model_dump(), "diff": result["stats"]}


@router.delete("/compare/release/{doc_id}")
def revoke_release(
    doc_id: str,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """撤销放行（放错了要能收回，否则又是一个单向门）。"""
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != current.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    rows = db.execute(
        select(DocumentRelease).where(DocumentRelease.document_id == doc.id)
    ).scalars().all()
    for r in rows:
        db.delete(r)
    from app.services.audit_service import write_audit

    write_audit(db, action="document_release_revoke", user_id=current.id,
                username=current.username, target=doc.filename,
                detail={"count": len(rows)})
    db.commit()
    return {"ok": True, "revoked": len(rows)}
