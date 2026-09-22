from app.db.session import SessionLocal
from app.models.document import DocumentTask
from app.tasks.reaper import enqueue_parse
import uuid
db = SessionLocal()
stuck = db.query(DocumentTask).filter(DocumentTask.status == "running").all()
for t in stuck:
    t.status = "pending"; t.celery_task_id = None
db.commit()
for t in stuck:
    enqueue_parse(t.id)
    print("REQUEUED", t.id)
