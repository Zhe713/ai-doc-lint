"""Day25 端到端验证：真实 4 份 ccgp 合同走 API 建组→触发 Celery 比对→轮询详情。"""
import json
import time

import requests

BASE = "http://nginx/api/v1"
DOC_IDS = [
    "f1975f20-e57d-40d4-b9c0-c2a3699e51d2",  # 东莞技师学院
    "5ddd4fbb-a613-4caf-b073-a8338e79253d",  # 始兴明德中学
    "310cad58-0dd9-468c-89cf-6cda2798715b",  # 肇庆高新区
    "0cdee310-dbd7-4b94-a6d2-a1f95deef2d3",  # 铜川营养餐
]

s = requests.Session()
r = s.post(f"{BASE}/auth/login", json={"username": "boss_admin", "password": "AdminPass123"}, timeout=10)
print("login:", r.status_code)
token = r.json()["access_token"]
H = {"Authorization": f"Bearer {token}"}

r = s.post(f"{BASE}/compare-groups",
           json={"name": "真实合同验收组（中国政府采购网 2026-10-08 公告×4）",
                 "document_ids": DOC_IDS},
           headers=H, timeout=10)
print("create group:", r.status_code, r.json().get("id", r.text[:80]))
gid = r.json()["id"]

r = s.post(f"{BASE}/compare-groups/{gid}/compare", headers=H, timeout=10)
print("trigger:", r.status_code, r.text[:80])

for i in range(40):
    time.sleep(3)
    r = s.get(f"{BASE}/compare-groups/{gid}", headers=H, timeout=10)
    d = r.json()
    if d["status"] == "parsed":
        print("group status: parsed")
        print("stats:", json.dumps(d["stats"], ensure_ascii=False))
        print("documents:", len(d["documents"]))
        print("matrix fields:", sorted(d["matrix"].keys()))
        print("findings:", len(d["findings"]))
        for f in d["findings"][:6]:
            print(" -", f["rule_id"], f["severity"], f["message"][:60])
        json.dump(d, open("/tmp/e2e_group_detail.json", "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("detail saved to /tmp/e2e_group_detail.json")
        break
    print(f"  poll {i}: status={d['status']} findings={len(d['findings'])}")
else:
    print("TIMEOUT waiting compare")
