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
    return {
        "document_id": doc.id,
        "total": len(rows),
        "items": [FindingOut.model_validate(f).model_dump() for f in rows],
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
    db.commit()
    db.refresh(finding)
    return finding
