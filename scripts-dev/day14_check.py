"""Day14 验证：L1/L2 路由分层、槽位补全、intent_routes 落库。"""
import io
import time

import httpx

BASE = "http://localhost:8000/api/v1"


def login():
    r = httpx.post(BASE + "/auth/login",
                   json={"username": "boss_admin", "password": "AdminPass123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload(name, *, doc_type="auto", checks=""):
    headers = login()
    data = {"doc_type": doc_type, "checks": checks}
    r = httpx.post(
        BASE + "/documents/upload", headers=headers, data=data,
        files={"files": (name, io.BytesIO("测试正文内容，用于意图路由验证。\n".encode()), "text/plain")},
    )
    return r.json()["group_id"], r.json()["tasks"][0]["document_id"]


def wait_group(group_id):
    from app.db.session import SessionLocal
    from app.models.document import DocumentTask
    for _ in range(40):
        db = SessionLocal()
        tasks = db.query(DocumentTask).filter(DocumentTask.group_id == group_id).all()
        reviews = db.query(DocumentTask).filter(
            DocumentTask.group_id.is_(None),
            DocumentTask.task_id.in_([t.id for t in tasks]),
        ).all() if False else []
        # review 任务无 group；按 document_id 查
        doc_ids = [t.document_id for t in tasks]
        from app.models.document import Document
        revs = db.query(DocumentTask).filter(
            DocumentTask.task_type == "review",
            DocumentTask.document_id.in_(doc_ids),
        ).all()
        done = all(t.status in ("parsed", "failed", "cancelled") for t in tasks) and all(
            r.status in ("parsed", "failed") for r in revs
        )
        if done and revs:
            out = []
            for t in tasks:
                doc = db.query(Document).filter(Document.id == t.document_id).one()
                rev = next(r for r in revs if r.document_id == doc.id)
                out.append((doc.filename, doc.doc_type, t.stats, rev.stats))
            db.close()
            return out
        db.close()
        time.sleep(1)
    raise AssertionError("timeout")


# 场景1：显式勾选 → L1_HIT
g1, _ = upload("采购合同.txt", doc_type="contract", checks="format,typo")
# 场景2：文件名命中投标，未勾检查项 → L1 部分 + L2 补 checks
g2, _ = upload("投标文件.txt")
# 场景3：无任何线索 → L2 全补
g3, _ = upload("最终版.txt")

rows = wait_group(g1) + wait_group(g2) + wait_group(g3)
for filename, doc_type, parse_stats, review_stats in rows:
    print(filename, "| doc_type:", doc_type,
          "| route:", parse_stats.get("route_path"),
          "| review checks:", review_stats.get("checks"))

m = {r[0]: r for r in rows}
assert m["采购合同.txt"][1] == "contract"
assert m["采购合同.txt"][2]["route_path"] == "L1_HIT"
assert m["投标文件.txt"][1] == "tender"
assert m["投标文件.txt"][2]["route_path"] == "L1_MISS->L2_HIT"
assert m["投标文件.txt"][3]["checks"] == ["format", "typo"]
assert m["最终版.txt"][1] == "general"
assert m["最终版.txt"][2]["route_path"] == "L1_MISS->L2_HIT"

# intent_routes 落库核验
from app.db.session import SessionLocal
from app.models.document import IntentRoute

db = SessionLocal()
for gid in (g1, g2, g3):
    routes = db.query(IntentRoute).filter(IntentRoute.session_id == str(gid)).all()
    assert len(routes) == 1, f"批次 {gid} 应各有 1 条路由记录"
    rt = routes[0]
    print("route row:", rt.domain, rt.final_layer, rt.path, rt.intent_code, rt.slots)
    assert rt.domain == "pipeline"
db.close()
print("DAY14 OK")
