"""Day15 浸泡：100 份文档同时受理，parse+review 全链路，计时并核对。"""
import io
import time

import httpx

BASE = "http://localhost:8000/api/v1"

r = httpx.post(BASE + "/auth/login",
               json={"username": "boss_admin", "password": "AdminPass123"})
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

files = []
for i in range(100):
    # 约 1/5 文档含已知错别字
    if i % 5 == 0:
        text = f"第{i}份文档\n少先队员因该为老人让坐，这是基本礼貌。\n双方签字盖章后生效。\n"
    else:
        text = f"第{i}份文档\n甲方与乙方就采购事宜达成一致，货物符合质量标准。\n双方签字盖章后生效。\n"
    files.append(("files", (f"soak15_{i:03d}.txt", io.BytesIO(text.encode()), "text/plain")))

t0 = time.perf_counter()
r = httpx.post(BASE + "/documents/upload", headers=headers, files=files, timeout=300)
print("upload", r.status_code, "in", round(time.perf_counter() - t0, 1), "s")
group_id = r.json()["group_id"]

from app.db.session import SessionLocal
from app.models.document import CheckFinding, Document, DocumentTask

while True:
    db = SessionLocal()
    parse_tasks = db.query(DocumentTask).filter(DocumentTask.group_id == group_id).all()
    doc_ids = [t.document_id for t in parse_tasks]
    review_tasks = db.query(DocumentTask).filter(
        DocumentTask.task_type == "review",
        DocumentTask.document_id.in_(doc_ids),
    ).all()
    p_done = all(t.status == "parsed" for t in parse_tasks)
    r_done = len(review_tasks) == 100 and all(t.status == "parsed" for t in review_tasks)
    if p_done and r_done:
        findings_count = (
            db.query(CheckFinding)
            .filter(CheckFinding.document_id.in_(doc_ids), CheckFinding.checker == "typo")
            .count()
        )
        db.close()
        break
    db.close()
    time.sleep(2)

elapsed = round(time.perf_counter() - t0, 1)
print(f"100 docs parse+review done in {elapsed}s; typo findings = {findings_count}")
assert findings_count >= 20, "20 份含错别字文档应各至少 1 命中"
print("DAY15 SOAK OK")
