"""解析任务：入队 → RUNNING → 调流水线 → PARSED/AWAITING/FAILED。

瞬时错误（MinIO 超时、进程被杀）由 celery acks_late + 退避重试兜住；
内容问题（损坏/扫描件/不支持格式）一律走人工闸门，不自动重试。
"""

import logging
import uuid

from celery.utils.log import get_task_logger

from app.db.session import SessionLocal
from app.models.document import STATUS_AWAITING, STATUS_PENDING, Document, DocumentTask
from app.services import task_state
from app.tasks.celery_app import celery_app
from app.tasks.parse_pipeline import run_parse_pipeline

logger = get_task_logger(__name__)
log = logging.getLogger("parse")


def _cancelled(db, task: DocumentTask) -> bool:
    db.refresh(task)
    return task.status == task_state.STATUS_CANCELLED


@celery_app.task(name="app.tasks.parse.run_parse", bind=True, max_retries=3)
def run_parse(self, task_id_str: str):
    db = SessionLocal()
    try:
        task = db.get(DocumentTask, uuid.UUID(task_id_str))
        if task is None:
            log.warning("task %s not found, skip", task_id_str)
            return
        if task.status not in (STATUS_PENDING, STATUS_AWAITING):
            log.info("task %s in status %s, skip", task_id_str, task.status)
            return

        task_state.change_status(
            db, task, task_state.STATUS_RUNNING,
            event_type="task_started", stage="init",
            message="开始受理解析", fields={"celery_task_id": self.request.id},
        )

        document = db.get(Document, task.document_id)
        if document is None:
            task_state.change_status(
                db, task, task_state.STATUS_FAILED,
                event_type="task_failed", stage="error", message="文档记录不存在",
            )
            return

        run_parse_pipeline(db, task, document)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("parse task %s failed: %s", task_id_str, exc)
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()
