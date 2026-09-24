"""卡死任务巡检与启动对账。

- reaper（beat 每 stalled_timeout/2 秒）：RUNNING 但心跳事件超时的任务判为僵尸，重新入队。
- worker_process_init：子进程启动时先 dispose 继承自父进程的连接池（防 fork 共享连接），
  并用 boot 级 Valkey 锁保证整组 worker 只做一次对账，把 Broker 丢失的任务重新投递。
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

import redis
from celery.signals import worker_process_init
from sqlalchemy import select

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.models.document import STATUS_PENDING, STATUS_RUNNING, DocumentTask, TaskEvent
from app.tasks.celery_app import QUEUE_PARSE, celery_app
from app.tasks.parse import run_parse

log = logging.getLogger("reaper")

# worker 本次启动的标识：父进程生成，所有 fork 出的子进程继承同一份（回收重建也不变）
_BOOT_ID = uuid.uuid4().hex
_RECONCILE_LOCK = f"lock:startup-reconcile:{_BOOT_ID}"
_RECONCILE_LOCK_TTL = 600


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


def _reconcile() -> int:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(DocumentTask).where(DocumentTask.status.in_([STATUS_PENDING, STATUS_RUNNING]))
        ).scalars().all()
        for task in rows:
            db.execute(
                DocumentTask.__table__.update()
                .where(DocumentTask.id == task.id)
                .values(status=STATUS_PENDING, celery_task_id=None)
            )
            enqueue_parse(task.id)
        db.commit()
        if rows:
            log.info("startup reconcile re-enqueued %d task(s)", len(rows))
        return len(rows)
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("startup reconcile failed")
        return 0
    finally:
        db.close()


@worker_process_init.connect
def init_worker_process(sender=None, **kwargs):
    # fork 之后：丢弃继承自父进程的连接池（空池时无任何流量），杜绝跨进程共享连接
    engine.dispose()

    # boot 级锁：本次 worker 启动只有一个子进程执行对账；回收重建的子进程不再重复
    try:
        client = redis.Redis.from_url(settings.valkey_url)
        if not client.set(_RECONCILE_LOCK, "1", nx=True, ex=_RECONCILE_LOCK_TTL):
            return
    except Exception:  # noqa: BLE001
        log.exception("reconcile lock failed, skip reconcile")
        return
    _reconcile()
