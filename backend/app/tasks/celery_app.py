"""Celery 应用：Valkey 作 Broker，DB 为任务事实源（不依赖 result backend）。

四条队列：parse（本周期启用，prefork 进程池跑 docling/OCR）、
review / annotate / learn（W4/W7 才会发任务，本周仅定义）。
"""

from celery import Celery
from kombu import Queue

from app.core.config import settings

QUEUE_PARSE = "parse"
QUEUE_REVIEW = "review"
QUEUE_ANNOTATE = "annotate"
QUEUE_LEARN = "learn"

celery_app = Celery(
    "ai_doc_lint",
    broker=settings.celery_broker_url,
    include=[
        "app.tasks.parse",
        "app.tasks.reaper",
        "app.tasks.review",
    ],
)

celery_app.conf.update(
    result_backend=None,  # 任务状态以 PostgreSQL 为准，不用 result backend
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_default_queue=QUEUE_PARSE,
    task_acks_late=True,
    worker_max_tasks_per_child=settings.parse_max_tasks_per_child,
    task_track_started=True,
    task_ignore_result=True,
    task_default_retry_delay=5,
)

celery_app.conf.task_queues = (
    Queue(QUEUE_PARSE, routing_key=QUEUE_PARSE),
    Queue(QUEUE_REVIEW, routing_key=QUEUE_REVIEW),
    Queue(QUEUE_ANNOTATE, routing_key=QUEUE_ANNOTATE),
    Queue(QUEUE_LEARN, routing_key=QUEUE_LEARN),
)

celery_app.conf.task_routes = {
    "app.tasks.parse.run_parse": {"queue": QUEUE_PARSE},
    "app.tasks.reaper.reap_stalled": {"queue": QUEUE_PARSE},
    "app.tasks.review.run_review": {"queue": QUEUE_REVIEW},
}

celery_app.conf.beat_schedule = {
    "reap-stalled": {
        "task": "app.tasks.reaper.reap_stalled",
        "schedule": settings.stalled_timeout_seconds / 2,
        "options": {"queue": QUEUE_PARSE},
    },
}
