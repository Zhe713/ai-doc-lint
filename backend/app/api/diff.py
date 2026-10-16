"""版本 diff 比对 API（P3-1）：两份文档的文本行级差异 + 无差异自动放行判定。

- 从 Artifact(plaintext) 取两份文档正文，difflib 行级对比；
- 返回逐行 type（equal/add/del）+ 统计（相同/新增/删除行数）+ identical；
- 无差异自动放行开关的判定在 API 层完成（identical=True 且 auto_bypass=True 时
  前端展示"可放行"徽标；批量矩阵报告的放行列由 P3-2 复用同一判定）。
"""

import difflib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db import storage
from app.db.session import get_db
from app.models.document import ART_PLAINTEXT, Artifact, Document
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

    truncated = False
    if len(text_a) > _MAX_DIFF_CHARS or len(text_b) > _MAX_DIFF_CHARS:
        truncated = True
        text_a = text_a[:_MAX_DIFF_CHARS]
        text_b = text_b[:_MAX_DIFF_CHARS]

    lines_a = text_a.splitlines()
    lines_b = text_b.splitlines()
    # 行级 diff（保留尾部差异细节）
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
        "doc_a": {"id": doc_a_id, "filename": fn_a, "chars": len(text_a)},
        "doc_b": {"id": doc_b_id, "filename": fn_b, "chars": len(text_b)},
        "identical": identical,
        "auto_bypass": auto_bypass,
        "bypass_ready": identical and auto_bypass,
        "stats": {"same_lines": same_lines, "add_lines": add_lines,
                  "del_lines": del_lines, "changed_ratio": round(
                      (add_lines + del_lines) / max(same_lines + add_lines + del_lines, 1), 4)},
        "truncated": truncated,
        "rows": rows,
    }
