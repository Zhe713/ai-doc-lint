from app.db.session import SessionLocal
from app.core.security import create_access_token
from app.models.user import User
from app.models.document import DocumentTask, Document
db = SessionLocal(); u = db.query(User).first()
print(create_access_token(str(u.id))[0])
rows = db.query(DocumentTask, Document).join(Document, Document.id==DocumentTask.document_id).filter(Document.filename=='_sample.docx', DocumentTask.status=='awaiting_decision').all()
for t,d in rows: print('DOCX_TASK', t.id, 'reason', t.gate_reason, 'payload', t.gate_payload)
