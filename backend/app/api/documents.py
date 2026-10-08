"""文档受理 / 任务查询 / 取消 / 闸门决策接口（W2 Day7）。"""

import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.config import settings
from app.db import storage
from app.db.session import get_db
from app.models.document import (
    GATE_CONTINUE_WARNINGS,
    GATE_CANCEL,
    GATE_OCR_REQUIRED,
    GATE_RETRY_OCR,
    GATE_UNSUPPORTED,
    STATUS_AWAITING,
    STATUS_CANCELLED,
    STATUS_PARSED,
    STATUS_PENDING,
    Document,
    DocumentTask,
    TaskEvent,
    TaskGroup,
)
from app.models.user import User
from app.schemas.task import (
    DecisionIn,
    TaskDetailOut,
    TaskEventOut,
    TaskGroupOut,
    TaskOut,
    UploadOut,
    UploadedTaskOut,
)
from app.services import task_state
from app.router.pipeline_router import route_pipeline
from app.tasks.celery_app import QUEUE_PARSE
from app.tasks.events import append_event
from app.tasks.reaper import enqueue_parse

router = APIRouter(tags=["documents"])

ALLOWED_EXT = {"docx", "pdf", "txt", "md"}
LEGACY_EXT = {"doc"}
MAX_BATCH = 100
PENDING_QUOTA = 100


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _pending_count(db: Session, user_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count(DocumentTask.id)).where(
            DocumentTask.user_id == user_id, DocumentTask.status.in_([STATUS_PENDING, task_state.STATUS_RUNNING])
        )
    ).scalar_one()


def _get_owned_task(db: Session, user: User, task_id: uuid.UUID) -> DocumentTask:
    task = db.get(DocumentTask, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.get("/documents/{doc_id}/fields")
def list_fields(
    doc_id: uuid.UUID, db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    doc = _get_owned_document(db, current, doc_id)
    from app.models.document import DocumentField

    rows = db.execute(
        select(DocumentField)
        .where(DocumentField.document_id == doc.id)
        .order_by(DocumentField.id)
    ).scalars().all()
    return [_field_dict(r) for r in rows]


@router.post("/documents/{doc_id}/extract", status_code=200)
def extract_fields(
    doc_id: uuid.UUID, db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    doc = _get_owned_document(db, current, doc_id)
    from app.extract.field_extractor import FieldExtractor

    extractor = FieldExtractor(db, doc, allow_llm=True)
    fields = extractor.run()
    db.commit()
    return {"fields": [_field_dict(f) for f in fields],
            "warnings": extractor.warnings}


def _get_owned_document(db: Session, user: User,
                        doc_id: uuid.UUID):
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user.id:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


def _field_dict(row) -> dict:
    return {
        "id": row.id,
        "document_id": str(row.document_id),
        "field_key": row.field_key,
        "field_label": row.field_label,
        "value_type": row.value_type,
        "value_text": row.value_text,
        "value_number": row.value_number,
        "value_date": row.value_date.isoformat() if row.value_date else None,
        "confidence": row.confidence,
        "source": row.source,
        "location": row.location,
    }


@router.post("/documents/upload", response_model=UploadOut, status_code=201)
async def upload_documents(
    files: list[UploadFile] = File(...),
    doc_type: str = Form("auto"),
    checks: str = Form(""),
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> UploadOut:
    if not files:
        raise HTTPException(status_code=422, detail="请至少选择一个文件")
    if len(files) > MAX_BATCH:
        raise HTTPException(status_code=422, detail=f"单次最多 {MAX_BATCH} 份")

    # 配额：个人档同时在途（排队+运行）任务上限
    in_flight = _pending_count(db, current.id)
    if in_flight + len(files) > PENDING_QUOTA:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=f"当前在途任务 {in_flight} 个，已达上限 {PENDING_QUOTA}")

    group = TaskGroup(user_id=current.id, total=len(files))
    db.add(group)
    db.flush()

    created: list[UploadedTaskOut] = []
    for f in files:
        ext = _ext(f.filename or "")
        if ext in LEGACY_EXT:
            raise HTTPException(status_code=422, detail=f"暂不支持老格式 .doc，请另存为 .docx 后再上传（{f.filename}）")
        if ext not in ALLOWED_EXT:
            raise HTTPException(status_code=422, detail=f"不支持的格式 .{ext}（{f.filename}），支持：{', '.join(sorted(ALLOWED_EXT))}")

        data = await f.read()
        if len(data) == 0:
            raise HTTPException(status_code=422, detail=f"空文件：{f.filename}")
        if len(data) > 200 * 1024 * 1024:
            raise HTTPException(status_code=422, detail=f"文件超过 200MB：{f.filename}")

        digest = hashlib.sha256(data).hexdigest()
        key = f"docs/{current.id}/{uuid.uuid4().hex}/{f.filename}"
        storage.put_object(key, data, content_type=f.content_type)

        route = route_pipeline(
            db, user=current, session_id=str(group.id),
            filename=f.filename or "",
            options={"doc_type": doc_type, "checks": checks},
            default_checks=settings.default_checks,
        )

        doc = Document(
            user_id=current.id,
            filename=f.filename or "unnamed",
            storage_key=key,
            sha256=digest,
            size_bytes=len(data),
            content_type=f.content_type,
            ext=ext,
            doc_type=route.slots["doc_type"],
        )
        db.add(doc)
        db.flush()

        task = DocumentTask(
            document_id=doc.id, user_id=current.id, group_id=group.id, task_type="parse",
            stats={
                "checks": route.slots["checks"],
                "doc_type": route.slots["doc_type"],
                "route_layer": route.layer,
                "route_path": route.path,
            },
        )
        db.add(task)
        group.pending += 1
        db.flush()
        created.append(UploadedTaskOut(task_id=task.id, document_id=doc.id, filename=doc.filename, status=task.status))

    db.commit()
    for item in created:
        enqueue_parse(item.task_id)

    return UploadOut(group_id=group.id, total=len(created), tasks=created)


@router.get("/task-groups", response_model=list[TaskGroupOut])
def list_groups(db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    rows = db.execute(
        select(TaskGroup).where(TaskGroup.user_id == current.id).order_by(TaskGroup.created_at.desc()).limit(50)
    ).scalars().all()
    return rows


@router.get("/task-groups/{group_id}", response_model=dict)
def group_detail(group_id: uuid.UUID, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    group = db.get(TaskGroup, group_id)
    if group is None or group.user_id != current.id:
        raise HTTPException(status_code=404, detail="任务组不存在")
    tasks = db.execute(
        select(DocumentTask, Document.filename)
        .join(Document, Document.id == DocumentTask.document_id)
        .where(DocumentTask.group_id == group_id)
        .order_by(DocumentTask.created_at)
    ).all()
    return {
        "group": TaskGroupOut.model_validate(group).model_dump(),
        "tasks": [
            TaskOut(
                id=t.id,
                document_id=t.document_id,
                group_id=t.group_id,
                filename=fn,
                task_type=t.task_type,
                status=t.status,
                gate_reason=t.gate_reason,
                gate_payload=t.gate_payload,
                warnings=t.warnings,
                stats=t.stats,
                error_code=t.error_code,
                error_message=t.error_message,
                created_at=t.created_at,
                updated_at=t.updated_at,
            ).model_dump()
            for t, fn in tasks
        ],
    }


@router.get("/tasks/{task_id}", response_model=TaskDetailOut)
def task_detail(task_id: uuid.UUID, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    task = _get_owned_task(db, current, task_id)
    doc = db.get(Document, task.document_id)
    events = db.execute(
        select(TaskEvent).where(TaskEvent.task_id == task.id).order_by(TaskEvent.id.desc()).limit(50)
    ).scalars().all()
    return TaskDetailOut(
        id=task.id,
        document_id=task.document_id,
        group_id=task.group_id,
        filename=doc.filename if doc else "-",
        task_type=task.task_type,
        status=task.status,
        gate_reason=task.gate_reason,
        gate_payload=task.gate_payload,
        warnings=task.warnings,
        stats=task.stats,
        error_code=task.error_code,
        error_message=task.error_message,
        created_at=task.created_at,
        updated_at=task.updated_at,
        events=[TaskEventOut.model_validate(e) for e in reversed(events)],
    )


@router.get("/tasks/{task_id}/preview")
def task_preview(task_id: uuid.UUID, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    task = _get_owned_task(db, current, task_id)
    refs = task.result_refs or {}
    key = refs.get("plaintext")
    if not key:
        raise HTTPException(status_code=409, detail="任务尚未解析出文本")
    text = storage.get_object_bytes(key).decode("utf-8", errors="replace")
    limit = 20000
    truncated = len(text) > limit
    doc = db.get(Document, task.document_id)
    return {
        "filename": doc.filename if doc else "-",
        "plaintext": text[:limit],
        "truncated": truncated,
        "total_chars": len(text),
        "stats": task.stats,
    }


@router.post("/tasks/{task_id}/cancel", status_code=200)
def cancel_task(task_id: uuid.UUID, db: Session = Depends(get_db), current: User = Depends(get_current_user)):
    task = _get_owned_task(db, current, task_id)
    if task.status == STATUS_CANCELLED:
        return {"status": task.status}
    try:
        task_state.change_status(
            db, task, STATUS_CANCELLED, event_type="task_cancelled", stage="cancel", message="用户取消任务"
        )
    except task_state.IllegalTransition:
        raise HTTPException(status_code=409, detail=f"当前状态 {task.status} 不可取消")
    # 队列中/刚被领取的 Celery 任务撤销
    if task.celery_task_id:
        from app.tasks.celery_app import celery_app

        celery_app.control.revoke(task.celery_task_id, terminate=False, queue=QUEUE_PARSE)
    return {"status": task.status}


@router.post("/tasks/{task_id}/decision", status_code=200)
def decide_gate(
    task_id: uuid.UUID,
    body: DecisionIn,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    task = _get_owned_task(db, current, task_id)
    if task.status != STATUS_AWAITING:
        raise HTTPException(status_code=409, detail=f"任务不在待决策状态（当前 {task.status}）")

    if body.action == GATE_CANCEL:
        task_state.change_status(
            db, task, STATUS_CANCELLED, event_type="gate_decision", stage="cancel", message="用户选择取消重传"
        )
    elif body.action == GATE_CONTINUE_WARNINGS:
        # “带警告继续”仅对解析失败/低置信度开放；缺 OCR、格式不支持必须先处理
        if task.gate_reason in (GATE_OCR_REQUIRED, GATE_UNSUPPORTED):
            raise HTTPException(
                status_code=409,
                detail=f"当前闸门原因 {task.gate_reason} 不允许带警告继续，请选择 OCR 重试或取消",
            )
        warnings = list(task.warnings or [])
        warnings.append({"code": "user_continued_with_warning", "reason": task.gate_reason})
        task_state.change_status(
            db, task, STATUS_PARSED,
            event_type="gate_decision", stage="done",
            message="用户选择带覆盖警告继续",
            fields={"warnings": warnings, "gate_reason": None, "gate_payload": None},
        )
    elif body.action == GATE_RETRY_OCR:
        # 回到 pending 重新入队（强制 OCR 在 Day8 由 attempts/标记控制）
        task_state.change_status(
            db, task, STATUS_PENDING,
            event_type="gate_decision", stage="retry",
            message="用户选择 OCR 重试",
            fields={
                "attempts": task.attempts + 1,
                "gate_reason": None,
                "gate_payload": None,
                "error_code": None,
                "error_message": None,
            },
        )
        db.commit()
        enqueue_parse(task.id)
    return {"status": task.status, "action": body.action}
