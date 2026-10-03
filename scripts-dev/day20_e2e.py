"""Day20 W4 整体验收（真实 LLM key）：
A. 好合同 docx 条款 0 漏报误报；缺条款 docx 逐类命中；
B. 100 份合同 clause 全链路浸泡，记录耗时与 token。
"""

import io
import time

import httpx
from docx import Document as DocxDocument

BASE = "http://localhost:8000/api/v1"

r = httpx.post(BASE + "/auth/login",
               json={"username": "boss_admin", "password": "AdminPass123"})
headers = {"Authorization": f"Bearer {r.json()['access_token']}"}


def docx_bytes(paragraphs: list[str]) -> bytes:
    doc = DocxDocument()
    for p in paragraphs:
        doc.add_paragraph(p)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


GOOD = [
    "买卖合同",
    "甲方：某科技有限公司 乙方：某贸易有限公司",
    "第一条 合同标的：办公设备一批。",
    "第二条 数量：共计10台。",
    "第三条 合同总价：人民币伍万元整。",
    "第四条 交付时间：签订后10日内交付。",
    "第五条 违约责任：违约方支付违约金并赔偿损失。",
    "第六条 争议解决：提交仲裁委员会仲裁。",
    "本合同自盖章之日起生效。",
]
BAD = [
    "协议",
    "甲方：某公司 乙方：某商行",
    "第一条 标的：办公用品。",
    "第二条 数量：5箱。",
    "第四条 交付时间：另行通知。",
    "本协议自盖章之日起生效。",
]


def upload(name, data):
    files = {"files": (name, io.BytesIO(data),
                       "application/vnd.openxmlformats-officedocument"
                       ".wordprocessingml.document")}
    form = {"doc_type": "contract",
            "checks": ["format", "typo", "clause"]}
    resp = httpx.post(BASE + "/documents/upload", headers=headers,
                      files=files, data=form, timeout=120)
    assert resp.status_code == 201, resp.text
    return resp.json()["tasks"][0]["document_id"]


def wait_review(doc_id):
    import uuid

    from app.db.session import SessionLocal
    from app.models.document import DocumentTask

    while True:
        db = SessionLocal()
        t = db.query(DocumentTask).filter(
            DocumentTask.document_id == uuid.UUID(doc_id),
            DocumentTask.task_type == "review",
        ).one_or_none()
        db.close()
        if t is not None and t.status in ("parsed", "failed"):
            break
        time.sleep(2)
    resp = httpx.get(f"{BASE}/documents/{doc_id}/findings", headers=headers)
    return resp.json()["items"]


print("=== A. docx 条款 E2E ===")
good_id = upload("day20_good.docx", docx_bytes(GOOD))
bad_id = upload("day20_bad.docx", docx_bytes(BAD))

good_items = wait_review(good_id)
bad_items = wait_review(bad_id)

good_clause = [f for f in good_items if f["checker"] == "clause"]
bad_clause = [f for f in bad_items if f["checker"] == "clause"]
print("good contract clause findings:",
      [(f["rule_id"], f["severity"]) for f in good_clause])
print("bad contract clause findings:",
      [(f["rule_id"], f["severity"]) for f in bad_clause])

assert good_clause == [], "好合同不应出现条款问题"
bad_rule_ids = {f["rule_id"] for f in bad_clause}
assert {"clause.price", "clause.breach", "clause.dispute"} <= bad_rule_ids, \
    bad_rule_ids
print("A OK")

print("=== B. 100 份 clause 浸泡 ===")
from app.db.session import SessionLocal
from app.models.llm import LLMCallLog

db = SessionLocal()
before_logs = {row.id for row in db.query(LLMCallLog)
               .filter(LLMCallLog.scene == "clause").all()}
t_start = time.perf_counter()

files = []
for i in range(100):
    if i < 80:
        text = (
            f"第{i}份合同\n甲方某公司与乙方某公司。标的：货物。数量：1件。"
            "合同总价：100元。交付时间：10日内。"
            "违约责任：违约方支付违约金。争议解决：提交仲裁委员会仲裁。\n"
        )
    else:
        # 弱信号：仅「逾期」，无违约责任 strong；争议解决完全缺失
        text = (
            f"第{i}份合同\n甲方某公司与乙方某公司。标的：货物。数量：1件。"
            "合同总价：100元。交付时间：10日内。逾期交付的另行协商。\n"
        )
    files.append(("files", (f"clause20_{i:03d}.txt",
                            io.BytesIO(text.encode()), "text/plain")))

resp = httpx.post(
    BASE + "/documents/upload", headers=headers, files=files,
    data={"doc_type": "contract", "checks": ["clause"]}, timeout=300,
)
assert resp.status_code == 201, resp.text
group_id = resp.json()["group_id"]

from app.models.document import Document, DocumentTask

while True:
    db2 = SessionLocal()
    tasks = db2.query(DocumentTask).filter(
        DocumentTask.group_id == group_id).all()
    review = db2.query(DocumentTask).filter(
        DocumentTask.task_type == "review",
        DocumentTask.document_id.in_([t.document_id for t in tasks]),
    ).all()
    done = (len(tasks) == 100
            and all(t.status == "parsed" for t in tasks)
            and len(review) == 100
            and all(t.status == "parsed" for t in review))
    db2.close()
    if done:
        break
    time.sleep(3)

elapsed = round(time.perf_counter() - t_start, 1)

db3 = SessionLocal()
new_logs = db3.query(LLMCallLog).filter(
    LLMCallLog.scene == "clause",
    LLMCallLog.id.notin_(before_logs or [-1]),
).all()
total_tokens = sum(log.total_tokens for log in new_logs)
print(f"100 docs clause done in {elapsed}s; "
      f"LLM calls = {len(new_logs)}; tokens = {total_tokens}")
db3.close()
print("DAY20 E2E OK")
