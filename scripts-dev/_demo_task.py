"""W2 Day6 队列骨架端到端验证：建文档+任务并入队，打印任务 id 与最终状态。"""

import time

from app.db.session import SessionLocal
from app.models.document import Document, DocumentTask, STATUS_PENDING
from app.models.user import User
from app.tasks.reaper import enqueue_parse

db = SessionLocal()
u = db.query(User).first()
assert u is not None, "先创建一个用户"

d = Document(
    user_id=u.id,
    filename="demo.txt",
    storage_key="demo/demo.txt",
    sha256="0" * 64,
    size_bytes=12,
    ext="txt",
    content_type="text/plain",
)
db.add(d)
db.flush()
t = DocumentTask(document_id=d.id, user_id=u.id, task_type="parse", status=STATUS_PENDING)
db.add(t)
db.commit()
print("TASK_ID", t.id)
enqueue_parse(t.id)

# 轮询 15 秒
for i in range(15):
    time.sleep(1)
    db.refresh(t)
    print(f"t={i} status={t.status} celery={t.celery_task_id}")
    if t.status in ("parsed", "failed", "awaiting_decision"):
        break

events = t.task_events if hasattr(t, "task_events") else None
from app.models.document import TaskEvent

rows = db.query(TaskEvent).filter(TaskEvent.task_id == t.id).order_by(TaskEvent.id).all()
for r in rows:
    print("EVENT", r.event_type, r.stage, r.message)
print("FINAL", t.status, t.stats)
db.close()
