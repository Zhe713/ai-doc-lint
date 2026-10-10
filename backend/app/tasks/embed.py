"""embed 向量化任务（W6 Day27）：读 plaintext → 分块 → bge 本地向量化 → 幂等入库。

解析成功后由 parse_pipeline 创建并入队；模型经 ModelScope 懒加载（0 token）。
失败可重试（celery 自带）；重复执行先删旧块再写，保证幂等。
"""

import logging
import uuid

from app.db.session import SessionLocal
from app.models.document import (
    ART_PLAINTEXT,
    STATUS_FAILED,
    STATUS_PARSED,
    STATUS_PENDING,
    Artifact,
    Document,
    DocumentTask,
)
from app.services import task_state
from app.services.chunker import chunk_text
from app.services.embedder import encode
from app.tasks.celery_app import QUEUE_EMBED, celery_app
from app.tasks.events import append_event

logger = logging.getLogger("embed")
log = logging.getLogger("embed")


def create_embed_task(db, document: Document) -> DocumentTask | None:
    """解析成功后创建 embed 任务（幂等：已有未完成 embed 任务则不重复建）。"""
    existing = (
        db.query(DocumentTask)
        .filter(
            DocumentTask.document_id == document.id,
            DocumentTask.task_type == "embed",
            DocumentTask.status.in_([STATUS_PENDING, task_state.STATUS_RUNNING,
                                    task_state.STATUS_RETRYING]),
        )
        .first()
    )
    if existing is not None:
        return None
    task = DocumentTask(
        document_id=document.id,
        user_id=document.user_id,
        task_type="embed",
        status=STATUS_PENDING,
        max_attempts=2,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    enqueue_embed(task.id)
    return task


def enqueue_embed(task_id: uuid.UUID) -> None:
    run_embed.apply_async(args=[str(task_id)], queue=QUEUE_EMBED)


def _read_plaintext(db, document: Document) -> str:
    """读取文档 plaintext 产物；无产物抛 ValueError。"""
    from app.db import storage

    artifact = (
        db.query(Artifact)
        .filter(Artifact.document_id == document.id,
                Artifact.kind == ART_PLAINTEXT)
        .first()
    )
    if artifact is None:
        raise ValueError("plaintext artifact missing")
    return storage.get_object_bytes(artifact.storage_key).decode("utf-8", errors="replace")


def _do_embed(db, document: Document, chunks: list[str]) -> dict:
    """向量化核心（可测）：编码 → 幂等入库。返回 stats。"""
    from app.models.embed import DocumentChunk

    vectors = encode(chunks)
    if len(vectors) != len(chunks):
        raise RuntimeError("embedding 数量与分块数不一致")
    db.query(DocumentChunk).filter(
        DocumentChunk.document_id == document.id).delete()
    db.flush()
    for i, (text, vec) in enumerate(zip(chunks, vectors)):
        db.add(DocumentChunk(
            document_id=document.id, chunk_index=i,
            content=text, embedding=vec))
    db.commit()
    return {"chunks": len(chunks), "dim": len(vectors[0])}


@celery_app.task(name="app.tasks.embed.run_embed", bind=True, max_retries=2)
def run_embed(self, task_id_str: str):
    db = SessionLocal()
    try:
        task = db.get(DocumentTask, uuid.UUID(task_id_str))
        if task is None:
            log.warning("embed task %s not found, skip", task_id_str)
            return
        if task.status != STATUS_PENDING:
            log.info("embed task %s status %s, skip", task_id_str, task.status)
            return

        task_state.change_status(
            db, task, task_state.STATUS_RUNNING,
            event_type="task_started", stage="init",
            message="开始向量化",
            fields={"celery_task_id": self.request.id},
        )

        document = db.get(Document, task.document_id)
        if document is None:
            task_state.change_status(
                db, task, STATUS_FAILED,
                event_type="task_failed", stage="error",
                message="文档记录不存在",
            )
            return

        chunks = chunk_text(_read_plaintext(db, document))
        if not chunks:
            task_state.change_status(
                db, task, STATUS_FAILED,
                event_type="task_failed", stage="error",
                message="文档无可分块文本",
            )
            return

        append_event(db, task, "stage_progress", stage="embed",
                     message=f"分块 {len(chunks)} 段，开始向量化")
        db.commit()

        stats = _do_embed(db, document, chunks)
        task_state.change_status(
            db, task, STATUS_PARSED,
            event_type="task_succeeded", stage="done",
            message=f"向量化完成（{stats['chunks']} 块）",
            fields={"stats": stats},
        )
        log.info("embed task %s done: %s chunks", task_id_str, stats["chunks"])
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("embed task %s failed: %s", task_id_str, exc)
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()
