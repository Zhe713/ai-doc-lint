# -*- coding: utf-8 -*-
"""检查主库 check_findings.feedback_cause 列是否存在。"""
from sqlalchemy import text

from app.db.session import SessionLocal

db = SessionLocal()
try:
    row = db.execute(
        text("SELECT column_name FROM information_schema.columns "
             "WHERE table_name='check_findings' AND column_name='feedback_cause'")
    ).fetchone()
    print("feedback_cause exists:", bool(row))
finally:
    db.close()
