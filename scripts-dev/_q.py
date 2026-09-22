from app.db.session import SessionLocal
from app.models.document import DocumentTask
db = SessionLocal()
for tid in ["e1274529-4814-410f-afb9-e00953727b0a","13d8fcdd-7796-43d0-855b-ed0c33e90ba9","3967df0b-c93b-409f-81d7-d39db7a4207b"]:
    t = db.get(DocumentTask, __import__("uuid").UUID(tid))
    print(tid[:8], "status=", t.status, "celery=", t.celery_task_id, "attempts=", t.attempts, "gate=", t.gate_reason, "err=", (t.error_message or "")[:120])
