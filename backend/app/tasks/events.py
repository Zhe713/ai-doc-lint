"""任务事件：写 task_events 审计表 + Valkey pub/sub 实时推送（api 侧扇出到 WS）。"""

import json

import redis

from app.core.config import settings
from app.models.document import DocumentTask, TaskEvent

EVENT_CHANNEL = "aidoc:task-events"

_pub = redis.Redis.from_url(settings.valkey_url, decode_responses=False)


def publish_event(task: DocumentTask, event: dict) -> None:
    """best-effort 发布进度事件；发布失败不影响主流程。"""
    try:
        payload = json.dumps(event, ensure_ascii=False, default=str)
        _pub.publish(EVENT_CHANNEL, payload)
    except Exception:  # noqa: BLE001
        # 队列/存储暂时不可用时静默，审计表已落库，WS 轮询兜底
        pass


def append_event(
    db,
    task: DocumentTask,
    event_type: str,
    stage: str | None = None,
    message: str | None = None,
    payload: dict | None = None,
) -> TaskEvent:
    row = TaskEvent(
        task_id=task.id,
        event_type=event_type,
        stage=stage,
        message=message,
        payload=payload,
    )
    db.add(row)
    db.flush()
    publish_event(
        task,
        {
            "task_id": str(task.id),
            "group_id": str(task.group_id) if task.group_id else None,
            "user_id": str(task.user_id),
            "event_type": event_type,
            "stage": stage,
            "message": message,
            "payload": payload or {},
        },
    )
    return row
