"""findings 查询/状态处理、文档列表接口（W3 Day15）。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.document import (
    FINDING_STATUSES,
    CheckFinding,
    Document,
    DocumentTask,
)
from app.models.user import User
from app.core.deps import get_current_user
from app.schemas.finding import DocumentOut, FindingOut, FindingPatch

router = APIRouter(tags=["findings"])


def _get_owned_document(db: Session, user: User, doc_id: uuid.UUID) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@router.get("/documents", response_model=list[DocumentOut])
def list_documents(
    limit: int = 100,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    limit = min(max(limit, 1), 200)
    return db.execute(
        select(Document)
        .where(Document.user_id == current.id)
        .order_by(Document.created_at.desc())
        .limit(limit)
    ).scalars().all()


@router.get("/documents/{doc_id}/findings")
def list_findings(
    doc_id: uuid.UUID,
    checker: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    doc = _get_owned_document(db, current, doc_id)
    query = select(CheckFinding).where(CheckFinding.document_id == doc.id)
    if checker:
        query = query.where(CheckFinding.checker == checker)
    if severity:
        query = query.where(CheckFinding.severity == severity)
    if status:
        query = query.where(CheckFinding.status == status)
    query = query.order_by(
        CheckFinding.severity,  # error/warning/info 字典序不符预期，前端再分组
        CheckFinding.id,
    )
    rows = db.execute(query).scalars().all()
    # 文档级解析状态：供前端展示「带警告完成」「检查器降级」警示（P1-5/P2-8 修复）
    doc_flags = {"continued_with_warning": False, "checker_degraded": False, "checker_warning_detail": []}
    parse_task = db.execute(
        select(DocumentTask)
        .where(
            DocumentTask.document_id == doc.id,
            DocumentTask.task_type == "parse",
        )
        .order_by(DocumentTask.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if parse_task is not None:
        task_warnings = parse_task.warnings or []
        if any(isinstance(w, dict) and w.get("code") == "user_continued_with_warning" for w in task_warnings):
            doc_flags["continued_with_warning"] = True
        stats = parse_task.stats or {}
        cw = stats.get("checker_warnings") or []
        if cw:
            doc_flags["checker_degraded"] = True
            doc_flags["checker_warning_detail"] = cw
    return {
        "document_id": doc.id,
        "total": len(rows),
        "items": [FindingOut.model_validate(f).model_dump() for f in rows],
        "doc_flags": doc_flags,
    }


@router.patch("/findings/{finding_id}", response_model=FindingOut)
def patch_finding(
    finding_id: int,
    body: FindingPatch,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    finding = db.get(CheckFinding, finding_id)
    if finding is None or finding.user_id != current.id:
        raise HTTPException(status_code=404, detail="问题记录不存在")
    if body.status not in FINDING_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"非法状态，可选：{', '.join(FINDING_STATUSES)}"
        )
    finding.status = body.status
    # W7 反馈采集：reason 仅在明确反馈时写入（误报/确认有效/已修复）
    if body.feedback_reason:
        finding.feedback_reason = body.feedback_reason
    # W7-5 误报原因标签：仅误报反馈时可填；非误报时清空避免残留
    if body.feedback_reason == "false_positive":
        finding.feedback_cause = body.feedback_cause
    else:
        finding.feedback_cause = None
    db.commit()
    db.refresh(finding)
    return finding


# ---------------- P3-3 导出三件套：意见书 PDF / Excel 明细 ----------------

def _get_doc_findings(db: Session, user: User, doc_id: uuid.UUID) -> tuple[Document, list[CheckFinding]]:
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    findings = db.execute(
        select(CheckFinding).where(CheckFinding.document_id == doc.id)
        .order_by(CheckFinding.severity, CheckFinding.id)
    ).scalars().all()
    return doc, list(findings)


@router.get("/documents/{doc_id}/export/pdf")
def export_opinion_pdf(
    doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """《合同审查意见书》PDF（含高管摘要 + 问题清单）。"""
    from fastapi.responses import Response
    from urllib.parse import quote

    from app.services.export import opinion_pdf_bytes

    doc, findings = _get_doc_findings(db, current, doc_id)
    raw = opinion_pdf_bytes(doc, findings)
    base = quote(doc.filename.rsplit(".", 1)[0], safe="")
    return Response(
        content=raw,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{base}_%E6%84%8F%E8%A7%81%E4%B9%A6.pdf"},
    )


@router.get("/documents/{doc_id}/export/xlsx")
def export_findings_xlsx(
    doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """问题明细 Excel（明细表 + 汇总表）。"""
    from fastapi.responses import Response
    from urllib.parse import quote

    from app.services.export import findings_xlsx_bytes

    doc, findings = _get_doc_findings(db, current, doc_id)
    raw = findings_xlsx_bytes(doc, findings)
    base = quote(doc.filename.rsplit(".", 1)[0], safe="")
    return Response(
        content=raw,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{base}_%E6%98%8E%E7%BB%86.xlsx"},
    )


@router.get("/documents/{doc_id}/export/summary")
def get_export_summary(
    doc_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """高管摘要（JSON，供前端报告页顶部展示）。"""
    from app.services.export import executive_summary

    doc, findings = _get_doc_findings(db, current, doc_id)
    return {"summary": executive_summary(doc, findings)}
