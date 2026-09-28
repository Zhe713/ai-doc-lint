"""Day13 验证：错别字命中 + 术语白名单不误报。"""
import io
import time

import httpx

BASE = "http://localhost:8000/api/v1"


def login():
    r = httpx.post(BASE + "/auth/login",
                   json={"username": "boss_admin", "password": "AdminPass123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload_and_wait(name, text):
    headers = login()
    r = httpx.post(
        BASE + "/documents/upload", headers=headers,
        files={"files": (name, io.BytesIO(text.encode("utf-8")), "text/plain")},
    )
    doc_id = r.json()["tasks"][0]["document_id"]

    from app.db.session import SessionLocal
    from app.models.document import CheckFinding, DocumentTask

    for _ in range(60):
        db = SessionLocal()
        review = (
            db.query(DocumentTask)
            .filter(DocumentTask.document_id == doc_id, DocumentTask.task_type == "review")
            .one_or_none()
        )
        if review and review.status in ("parsed", "failed"):
            findings = db.query(CheckFinding).filter(CheckFinding.document_id == doc_id).all()
            data = [(f.location["snippet"], f.message) for f in findings]
            stats = review.stats
            db.close()
            return data, stats
        db.close()
        time.sleep(2)
    raise AssertionError("review timeout")


bad_text = "少先队员因该为老人让坐，这是大家都知道的基本礼貌，每个人都因该这样做。"
bad, bstats = upload_and_wait("day13_bad.txt", bad_text)
print("BAD findings:")
for snippet, msg in bad:
    print(" ", msg, "|", snippet)
print("BAD stats:", bstats)

joined = " ".join(msg for _, msg in bad)
assert "因该" in joined and "应该" in joined, "未命中 因该→应该"
assert "让坐" in joined and "让座" in joined, "未命中 让坐→让座"

good_text = "甲方依法行使抵销权，乙方承担瑕疵担保责任，任何一方不得主张诉讼时效抗辩。"
good, gstats = upload_and_wait("day13_good.txt", good_text)
print("GOOD findings:", good)
print("GOOD stats:", gstats)
assert len(good) == 0, f"术语白名单文档不应报错，实际: {good}"
print("DAY13 OK")
