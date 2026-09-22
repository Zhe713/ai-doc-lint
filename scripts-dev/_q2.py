from app.db.session import SessionLocal
from app.models.document import DocumentTask, Document
db = SessionLocal()
rows = db.query(DocumentTask).order_by(DocumentTask.created_at.desc()).limit(6).all()
for t in rows:
    d = db.get(Document, t.document_id)
    print(d.filename, "|", t.status, "|", t.gate_reason, "|", (t.error_message or "")[:80])
