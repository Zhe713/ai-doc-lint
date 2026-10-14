# -*- coding: utf-8 -*-
"""L1 业务场景集成测试：40 份 golden 检查结果采集与汇总。"""
import json
import os
import urllib.request

BASE = "http://localhost:8080"
GOLDEN_DIR = r"D:\projects\ai-doc-lint\corpus\acceptance_golden"
OUT = os.path.join(GOLDEN_DIR, "l1_results.json")


def api_login():
    body = json.dumps({"username": "boss_admin", "password": "AdminPass123"}).encode()
    req = urllib.request.Request(BASE + "/api/v1/auth/login", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def get(token, path):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    token = api_login()
    with open(os.path.join(GOLDEN_DIR, "golden_docs.json"), encoding="utf-8") as f:
        mapping = json.load(f)
    with open(os.path.join(GOLDEN_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = {m["file"]: m for m in json.load(f)}

    rows = []
    for fname, doc_id in mapping.items():
        docs = get(token, "/api/v1/documents")
        doc = next((d for d in docs if str(d["id"]) == doc_id), None)
        status = doc.get("status") if doc else "unknown"
        rec = {"file": fname, "doc_id": doc_id, "status": status,
               "title": manifest[fname]["title"], "category": manifest[fname]["category"]}
        if status == "parsed":
            try:
                f = get(token, f"/api/v1/documents/{doc_id}/findings")
                items = f.get("items", [])
                sev = {}
                chk = {}
                for it in items:
                    sev[it.get("severity", "?")] = sev.get(it.get("severity", "?"), 0) + 1
                    chk[it.get("checker", "?")] = chk.get(it.get("checker", "?"), 0) + 1
                rec["findings_total"] = f.get("total", len(items))
                rec["severity"] = sev
                rec["checkers"] = chk
                rec["sample"] = [{"severity": it.get("severity"), "checker": it.get("checker"),
                                  "title": (it.get("title") or "")[:60],
                                  "message": (it.get("message") or "")[:90]} for it in items[:3]]
            except Exception as e:
                rec["error"] = str(e)
        rows.append(rec)

    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(rows, fp, ensure_ascii=False, indent=2)

    parsed = [r for r in rows if r["status"] == "parsed"]
    failed = [r for r in rows if r["status"] == "failed"]
    print(f"total={len(rows)} parsed={len(parsed)} failed={len(failed)} pending={len(rows)-len(parsed)-len(failed)}")
    if parsed:
        total_f = sum(r.get("findings_total", 0) for r in parsed)
        avg = total_f / len(parsed)
        sev_all = {}
        for r in parsed:
            for k, v in r.get("severity", {}).items():
                sev_all[k] = sev_all.get(k, 0) + v
        print(f"findings_total={total_f} avg_per_doc={avg:.1f} severity={sev_all}")
        print(f"output={OUT}")


if __name__ == "__main__":
    main()
