"""Day11 验证：上传 1 份 txt，确认 parse parsed 后自动产生 review 任务并 parsed。"""
import io
import time

import httpx

BASE = "http://localhost:8000/api/v1"

r = httpx.post(BASE + "/auth/login", json={"username": "boss_admin", "password": "AdminPass123"})
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

content = "货物买卖合同\n甲方：测试公司\n乙方：示例公司\n双方签字盖章后生效。\n".encode("utf-8")
r = httpx.post(
    BASE + "/documents/upload",
    headers=headers,
    files={"files": ("day11.txt", io.BytesIO(content), "text/plain")},
)
print("upload", r.status_code)
doc_id = r.json()["tasks"][0]["document_id"]

from app.db.session import SessionLocal
from app.models.document import DocumentTask

for _ in range(30):
    db = SessionLocal()
    rows = db.query(DocumentTask).filter(DocumentTask.document_id == doc_id).all()
    states = [(row.task_type, row.status) for row in rows]
    stats = {row.task_type: row.stats for row in rows}
    db.close()
    if len(rows) >= 2 and all(s in ("parsed", "failed", "cancelled") for _, s in states):
        break
    time.sleep(1)

print("states:", states)
print("stats:", stats)
assert ("parse", "parsed") in states
assert ("review", "parsed") in states
print("DAY11 OK")
