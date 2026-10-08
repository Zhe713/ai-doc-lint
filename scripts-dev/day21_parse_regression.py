"""Day21 真实合同解析回归：4 份政采中文合同 + 1 份官方示范合同 PDF
+ 50 份 CUAD 真实合同，全部为网络公开渠道获取的真实文件（非 AI 生成）。
只跑解析（不跑检查器），统计解析状态分布与失败原因。

容器内：python day21_parse_regression.py
"""

import io
import time
from pathlib import Path

import httpx

BASE = "http://localhost:8000/api/v1"

r = httpx.post(BASE + "/auth/login",
               json={"username": "boss_admin", "password": "AdminPass123"})
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

MIME = {".txt": "text/plain", ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument."
                 "wordprocessingml.document"}

ccgp = sorted(Path("/tmp/corpus/ccgp").glob("*.txt"))
tpl = sorted(Path("/tmp/corpus/templates").glob("*.pdf"))
cuad = sorted(Path("/tmp/corpus/cuad").glob("*.txt"))[:50]
paths = ccgp + tpl + cuad
print(f"ccgp={len(ccgp)}, templates={len(tpl)}, cuad={len(cuad)}, "
      f"total={len(paths)}")

files = []
for p in paths:
    files.append(("files", (p.name, io.BytesIO(p.read_bytes()),
                            MIME.get(p.suffix, "application/octet-stream"))))
resp = httpx.post(
    BASE + "/documents/upload", headers=headers, files=files,
    data={"doc_type": "contract", "checks": "none"}, timeout=600)
assert resp.status_code == 201, resp.text
groups = [resp.json()["group_id"]]

from app.db.session import SessionLocal
from app.models.document import DocumentTask

t0 = time.perf_counter()
while True:
    db = SessionLocal()
    tasks = db.query(DocumentTask).filter(
        DocumentTask.group_id.in_(groups)).all()
    doc_ids = [t.document_id for t in tasks]
    review = db.query(DocumentTask).filter(
        DocumentTask.task_type == "review",
        DocumentTask.document_id.in_(doc_ids),
    ).all()
    done = (len(tasks) == len(paths)
            and all(t.status in ("parsed", "failed") for t in tasks)
            and len(review) == len(tasks)
            and all(t.status in ("parsed", "failed") for t in review))
    db.close()
    if done:
        break
    time.sleep(3)

elapsed = round(time.perf_counter() - t0, 1)

db = SessionLocal()
tasks = db.query(DocumentTask).filter(
    DocumentTask.group_id.in_(groups),
    DocumentTask.task_type == "parse",
).all()
from collections import Counter

status_dist = Counter(t.status for t in tasks)
gate_dist: Counter = Counter()
errors: list[str] = []
for t in tasks:
    if t.status == "awaiting_decision":
        gate_dist[(t.stats or {}).get("gate", "?")] += 1
    if t.status == "failed":
        errors.append(f"{t.document_id}: {(t.error or '')[:120]}")

print(f"parse done in {elapsed}s for {len(tasks)} real contracts")
print("status distribution:", dict(status_dist))
print("gate distribution:", dict(gate_dist))
for e in errors[:10]:
    print("FAIL", e)

parsed_rate = round(status_dist.get("parsed", 0) / len(tasks) * 100, 1)
print(f"parsed rate: {parsed_rate}%")
assert parsed_rate >= 98, f"真实合同解析通过率过低: {parsed_rate}%"
print("DAY21 PARSE REGRESSION OK")
