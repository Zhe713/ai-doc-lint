"""比对组 API（W5 Day24）：创建/列表/详情/触发跨文档比对/删除。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.document import (
    STATUS_PENDING,
    CheckFinding,
    CompareGroup,
    CompareGroupDocument,
    Document,
    DocumentField,
    DocumentTask,
)
from app.models.user import User
from app.services import task_state
from app.tasks.cross_compare import enqueue_cross_compare

router = APIRouter(tags=["compare"])

MIN_DOCS = 2
MAX_DOCS = 20


def _get_owned_group(db: Session, user: User, group_id: uuid.UUID) -> CompareGroup:
    group = db.get(CompareGroup, group_id)
    if group is None or group.user_id != user.id:
        raise HTTPException(status_code=404, detail="比对组不存在")
    return group


def _group_out(db: Session, group: CompareGroup) -> dict:
    doc_count = db.execute(
        select(func.count(CompareGroupDocument.id))
        .where(CompareGroupDocument.compare_group_id == group.id)
    ).scalar_one()
    return {
        "id": str(group.id),
        "name": group.name,
        "status": group.status,
        "doc_count": doc_count,
        "stats": group.stats,
        "created_at": group.created_at.isoformat() if group.created_at else None,
        "finished_at": group.finished_at.isoformat() if group.finished_at else None,
    }


def _document_summary(db: Session, doc: Document) -> dict:
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "doc_type": doc.doc_type,
        "status": doc.status,
    }


@router.post("/compare-groups", status_code=201)
def create_compare_group(
    body: dict,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="比对组名称不能为空")
    doc_ids = body.get("document_ids") or []
    if not isinstance(doc_ids, list):
        raise HTTPException(status_code=422, detail="document_ids 必须是数组")
    if len(doc_ids) < MIN_DOCS:
        raise HTTPException(status_code=422, detail=f"至少选择 {MIN_DOCS} 份文档")
    if len(doc_ids) > MAX_DOCS:
        raise HTTPException(status_code=422, detail=f"单组最多 {MAX_DOCS} 份文档")
    seen: set[str] = set()
    docs: list[Document] = []
    for did in doc_ids:
        key = str(did)
        if key in seen:
            raise HTTPException(status_code=422, detail=f"文档 {key} 重复选择")
        seen.add(key)
        try:
            d = db.get(Document, uuid.UUID(key))
        except (ValueError, TypeError):
            raise HTTPException(status_code=422, detail=f"文档 ID 非法: {key}")
        if d is None or d.user_id != current.id:
            raise HTTPException(status_code=404, detail=f"文档 {key} 不存在")
        docs.append(d)

    group = CompareGroup(user_id=current.id, name=name, status="pending")
    db.add(group)
    db.flush()
    for pos, d in enumerate(docs):
        db.add(CompareGroupDocument(
            compare_group_id=group.id, document_id=d.id, position=pos))
    db.commit()
    db.refresh(group)

    # P1-1：建组即自动入队，避免"创建后卡 pending 需手动触发"
    first = db.execute(
        select(CompareGroupDocument)
        .where(CompareGroupDocument.compare_group_id == group.id)
        .order_by(CompareGroupDocument.position)
    ).scalars().first()
    task = DocumentTask(
        group_id=None,
        document_id=first.document_id,
        user_id=current.id,
        task_type="cross_compare",
        status=STATUS_PENDING,
        max_attempts=1,
        stats={"compare_group_id": str(group.id)},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    group.status = STATUS_PENDING
    db.commit()
    enqueue_cross_compare(task.id)

    return _group_out(db, group)


@router.get("/compare-groups")
def list_compare_groups(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    rows = db.execute(
        select(CompareGroup)
        .where(CompareGroup.user_id == current.id)
        .order_by(CompareGroup.created_at.desc())
    ).scalars().all()
    return [_group_out(db, g) for g in rows]


@router.get("/compare-groups/{group_id}")
def compare_group_detail(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    group = _get_owned_group(db, current, group_id)
    links = db.execute(
        select(CompareGroupDocument)
        .where(CompareGroupDocument.compare_group_id == group.id)
        .order_by(CompareGroupDocument.position)
    ).scalars().all()
    docs = [db.get(Document, l.document_id) for l in links]
    docs = [d for d in docs if d is not None]

    # 字段矩阵：field_key -> {doc_id: {value_text/value_number/value_date}}
    field_rows = db.execute(
        select(DocumentField).where(
            DocumentField.document_id.in_([d.id for d in docs]))
    ).scalars().all()
    matrix: dict[str, dict[str, dict]] = {}
    field_labels: dict[str, str] = {}
    for r in field_rows:
        cell = {
            "value_text": r.value_text,
            "value_number": r.value_number,
            "value_date": r.value_date.isoformat() if r.value_date else None,
            "source": r.source,
            "confidence": r.confidence,
        }
        matrix.setdefault(r.field_key, {})[str(r.document_id)] = cell
        field_labels.setdefault(r.field_key, r.field_label)

    findings = db.execute(
        select(CheckFinding).where(
            CheckFinding.task_id.in_(
                select(DocumentTask.id).where(
                    DocumentTask.user_id == current.id,
                    DocumentTask.stats["compare_group_id"].astext == str(group.id),
                )
            ),
            CheckFinding.checker == "cross_doc",
        ).order_by(CheckFinding.id)
    ).scalars().all()

    return {
        **_group_out(db, group),
        "documents": [_document_summary(db, d) for d in docs],
        "matrix": matrix,
        "field_labels": field_labels,
        "findings": [
            {
                "id": f.id,
                "rule_id": f.rule_id,
                "severity": f.severity,
                "message": f.message,
                "suggestion": f.suggestion,
                "document_id": str(f.document_id),
                "related_document_id": str(f.related_document_id)
                if f.related_document_id else None,
            }
            for f in findings
        ],
    }


@router.post("/compare-groups/{group_id}/compare", status_code=202)
def trigger_compare(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    group = _get_owned_group(db, current, group_id)
    if group.status == task_state.STATUS_RUNNING:
        raise HTTPException(status_code=409, detail="该比对组正在比对中")
    doc_count = db.execute(
        select(func.count(CompareGroupDocument.id))
        .where(CompareGroupDocument.compare_group_id == group.id)
    ).scalar_one()
    if doc_count < MIN_DOCS:
        raise HTTPException(status_code=422, detail=f"至少选择 {MIN_DOCS} 份文档")

    # 以首份文档为任务载体（任务状态机要求 document_id 非空）
    first = db.execute(
        select(CompareGroupDocument)
        .where(CompareGroupDocument.compare_group_id == group.id)
        .order_by(CompareGroupDocument.position)
    ).scalars().first()

    task = DocumentTask(
        group_id=None,
        document_id=first.document_id,
        user_id=current.id,
        task_type="cross_compare",
        status=STATUS_PENDING,
        max_attempts=1,
        stats={"compare_group_id": str(group.id)},
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    group.status = STATUS_PENDING
    db.commit()

    enqueue_cross_compare(task.id)
    return {"task_id": str(task.id), "group_id": str(group.id), "status": "queued"}


@router.delete("/compare-groups/{group_id}", status_code=204)
def delete_compare_group(
    group_id: uuid.UUID,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    group = _get_owned_group(db, current, group_id)
    db.delete(group)
    db.commit()
    return None
