"""卡死任务巡检与启动对账。

- reaper（beat 每 stalled_timeout/2 秒）：RUNNING 但心跳事件超时的任务判为僵尸，重新入队。
- worker_ready：worker 启动时把 Broker 丢失的 PENDING/RUNNING 任务重新投递（容器重启不丢活）。
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from celery.signals import worker_ready
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import STATUS_PENDING, STATUS_RUNNING, DocumentTask, TaskEvent
from app.tasks.celery_app import QUEUE_PARSE, celery_app
from app.tasks.parse import run_parse

log = logging.getLogger("reaper")


def latest_event_at(db, task_id: uuid.UUID) -> datetime | None:
    row = db.execute(
        select(TaskEvent.created_at)
        .where(TaskEvent.task_id == task_id)
        .order_by(TaskEvent.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row


def enqueue_parse(task_id: uuid.UUID, celery_task_id: str | None = None) -> None:
    run_parse.apply_async(args=[str(task_id)], queue=QUEUE_PARSE, task_id=celery_task_id)


@celery_app.task(name="app.tasks.reaper.reap_stalled", ignore_result=True)
def reap_stalled() -> dict:
    db = SessionLocal()
    requeued = 0
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.stalled_timeout_seconds)
        running = db.execute(select(DocumentTask).where(DocumentTask.status == STATUS_RUNNING)).scalars().all()
        for task in running:
            last = latest_event_at(db, task.id)
            if last is None or last < cutoff:
                db.execute(
                    DocumentTask.__table__.update()
                    .where(DocumentTask.id == task.id)
                    .values(status=STATUS_PENDING, celery_task_id=None)
                )
                requeued += 1
                enqueue_parse(task.id)
        db.commit()
        if requeued:
            log.warning("reaper requeued %d stalled task(s)", requeued)
        return {"requeued": requeued}
    except Exception:  # noqa: BLE001
        db.rollback()
        raise
    finally:
        db.close()


@worker_ready.connect
def reconcile_on_startup(sender=None, **kwargs):
    db = SessionLocal()
    try:
        pending = db.execute(
            select(DocumentTask).where(DocumentTask.status.in_([STATUS_PENDING, STATUS_RUNNING]))
        ).scalars().all()
        for task in pending:
            db.execute(
                DocumentTask.__table__.update()
                .where(DocumentTask.id == task.id)
                .values(status=STATUS_PENDING, celery_task_id=None)
            )
            enqueue_parse(task.id)
        db.commit()
        if pending:
            log.info("startup reconcile re-enqueued %d task(s)", len(pending))
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("startup reconcile failed")
    finally:
        db.close()
