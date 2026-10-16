"""W9-2: 系统监控告警 - 阈值判定与定时巡检。

指标源：Valkey 队列深度（6 队列）+ PostgreSQL 任务状态分布。
判定为纯函数（便于测试）；巡检任务将新告警写入 alert_events 并审计留痕；
同一告警（alert_type+关键参数）在未解决前不重复写入。
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.config import settings
from app.core.ratelimit import get_redis
from app.db.session import SessionLocal
from app.models.alert import (
    ALERT_CRITICAL,
    ALERT_STATUS_ACTIVE,
    ALERT_WARNING,
    AlertEvent,
)
from app.models.document import DocumentTask, TaskEvent
from app.tasks.celery_app import QUEUE_LEARN, celery_app

log = logging.getLogger("alerting")

CELERY_QUEUES = ["parse", "review", "annotate", "learn", "cross_compare", "embed"]

# ---- 阈值（config 可覆盖） ----
def _queue_threshold() -> int:
    return getattr(settings, "alert_queue_depth_threshold", 50)


def _failure_rate_threshold() -> float:
    return getattr(settings, "alert_parse_failure_rate", 0.3)


def evaluate(queue_lengths: dict[str, int], failure_rate: float, stalled: int) -> list[dict]:
    """纯判定：返回告警事件字典列表（不入库）。"""
    alerts: list[dict] = []
    q_thr = _queue_threshold()
    for q, depth in queue_lengths.items():
        if q == "error":
            continue
        if depth > q_thr:
            alerts.append(
                {
                    "level": ALERT_WARNING,
                    "alert_type": "queue_backlog",
                    "message": f"队列“{q}”积压 {depth} 个任务（阈值 {q_thr}），处理速度可能跟不上",
                    "detail": {"queue": q, "depth": depth, "threshold": q_thr},
                }
            )
    f_thr = _failure_rate_threshold()
    if failure_rate > f_thr:
        alerts.append(
            {
                "level": ALERT_CRITICAL,
                "alert_type": "parse_failure",
                "message": f"近 1 小时解析失败率 {failure_rate:.0%}（阈值 {f_thr:.0%}），请检查上传文件质量或解析链路",
                "detail": {"failure_rate": round(failure_rate, 3), "threshold": f_thr},
            }
        )
    if stalled > 0:
        alerts.append(
            {
                "level": ALERT_WARNING,
                "alert_type": "task_stalled",
                "message": f"检测到 {stalled} 个卡死任务（运行超时），已尝试自动重新入队",
                "detail": {"stalled": stalled},
            }
        )
    return alerts


def _queue_lengths() -> dict[str, int]:
    try:
        r = get_redis()
        return {q: r.llen(q) for q in CELERY_QUEUES}
    except Exception:  # noqa: BLE001
        return {}


def _parse_failure_rate() -> float:
    """近 1 小时创建的任务中 failed 占比。"""
    try:
        with SessionLocal() as db:
            since = datetime.now(timezone.utc) - timedelta(hours=1)
            total = db.execute(
                select(func.count(DocumentTask.id)).where(DocumentTask.created_at >= since)
            ).scalar_one()
            if not total:
                return 0.0
            failed = db.execute(
                select(func.count(DocumentTask.id)).where(
                    DocumentTask.created_at >= since, DocumentTask.status == "failed"
                )
            ).scalar_one()
            return failed / total
    except Exception:  # noqa: BLE001
        return 0.0


def _stalled_count() -> int:
    """running 但心跳事件超过 stalled_timeout 的任务数。"""
    try:
        with SessionLocal() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.stalled_timeout_seconds)
            running = db.execute(
                select(DocumentTask.id).where(DocumentTask.status == "running")
            ).scalars().all()
            stalled = 0
            for task_id in running:
                last = db.execute(
                    select(TaskEvent.created_at)
                    .where(TaskEvent.task_id == task_id)
                    .order_by(TaskEvent.created_at.desc())
                    .limit(1)
                ).scalar_one_or_none()
                if last is None or last < cutoff:
                    stalled += 1
            return stalled
    except Exception:  # noqa: BLE001
        return 0


def _latest_open_keys(db) -> set[str]:
    """当前未解决告警的指纹（alert_type + queue/level），用于去重。"""
    rows = db.execute(
        select(AlertEvent).where(AlertEvent.status == ALERT_STATUS_ACTIVE)
    ).scalars().all()
    keys: set[str] = set()
    for row in rows:
        detail = row.detail or {}
        fp = row.alert_type
        if row.alert_type == "queue_backlog":
            fp = f"queue_backlog:{detail.get('queue', '')}"
        keys.add(fp)
    return keys


@celery_app.task(name="app.tasks.alerting.check_system_alerts", ignore_result=True)
def check_system_alerts() -> dict:
    """Beat 定时巡检（默认每 5 分钟）：超阈值写入告警事件 + 审计留痕。"""
    db = SessionLocal()
    written = 0
    try:
        ql = _queue_lengths()
        failure_rate = _parse_failure_rate()
        stalled = _stalled_count()
        alerts = evaluate(ql, failure_rate, stalled)
        open_keys = _latest_open_keys(db)
        for alert in alerts:
            fp = alert["alert_type"]
            if alert["alert_type"] == "queue_backlog":
                fp = f"queue_backlog:{alert['detail'].get('queue', '')}"
            if fp in open_keys:
                continue
            db.add(
                AlertEvent(
                    level=alert["level"],
                    alert_type=alert["alert_type"],
                    message=alert["message"],
                    detail=alert["detail"],
                )
            )
            written += 1
        if written:
            from app.services.audit_service import write_audit

            db.commit()
            write_audit(
                db, action="alert_raised", username="system",
                detail={"count": written, "types": [a["alert_type"] for a in alerts]},
            )
            db.commit()
            log.warning("alerting: %d new alert(s)", written)
        return {"written": written, "evaluated": len(alerts)}
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("alert check failed")
        raise
    finally:
        db.close()
