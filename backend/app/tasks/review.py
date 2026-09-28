"""review（校验）任务：pending → running → 顺序执行检查器 → parsed（findings 已入表）。

检查器在 review_pipeline 中按意图路由结果编排（Day12 格式、Day13 错别字）。
"""

import logging
import uuid

from app.db.session import SessionLocal
from app.models.document import Document, DocumentTask, STATUS_PENDING
from app.services import task_state
from app.tasks.celery_app import QUEUE_REVIEW, celery_app
from app.tasks.review_pipeline import run_review_pipeline

logger = logging.getLogger("review")
log = logging.getLogger("review")


def enqueue_review(task_id: uuid.UUID) -> None:
    run_review.apply_async(args=[str(task_id)], queue=QUEUE_REVIEW)


@celery_app.task(name="app.tasks.review.run_review", bind=True, max_retries=2)
def run_review(self, task_id_str: str):
    db = SessionLocal()
    try:
        task = db.get(DocumentTask, uuid.UUID(task_id_str))
        if task is None:
            log.warning("review task %s not found, skip", task_id_str)
            return
        if task.status != STATUS_PENDING:
            log.info("review task %s in status %s, skip", task_id_str, task.status)
            return

        task_state.change_status(
            db, task, task_state.STATUS_RUNNING,
            event_type="task_started", stage="init",
            message="开始校验",
            fields={"celery_task_id": self.request.id},
        )

        document = db.get(Document, task.document_id)
        if document is None:
            task_state.change_status(
                db, task, task_state.STATUS_FAILED,
                event_type="task_failed", stage="error", message="文档记录不存在",
            )
            return

        run_review_pipeline(db, task, document)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("review task %s failed: %s", task_id_str, exc)
        raise self.retry(exc=exc, countdown=5)
    finally:
        db.close()
