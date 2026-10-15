# -*- coding: utf-8 -*-
"""重跑 40 份 golden 的 typo 检查（修复后）。清旧 typo findings → create_review_task(checks=['typo'])。"""
import json
import uuid

from app.db.session import SessionLocal
from app.models.document import CheckFinding, Document
from app.services.review_service import create_review_task

mapping = json.load(open('/tmp/golden_docs.json', encoding='utf-8'))
db = SessionLocal()
ok = 0
try:
    for fname, doc_id in mapping.items():
        doc = db.get(Document, uuid.UUID(doc_id))
        if doc is None:
            print('MISSING', fname)
            continue
        n = db.query(CheckFinding).filter(
            CheckFinding.document_id == doc.id, CheckFinding.checker == 'typo'
        ).delete(synchronize_session=False)
        db.commit()
        create_review_task(db, doc, checks=['typo'])
        print('OK', fname, 'removed', n)
        ok += 1
finally:
    db.close()
print('enqueued', ok, '/', len(mapping))
