# -*- coding: utf-8 -*-
"""从文档列表 API 生成 golden 文件名→doc_id 映射，并轮询解析完成。"""
import json
import os
import time
import urllib.request

BASE = "http://localhost:8080"
GOLDEN_DIR = r"D:\projects\ai-doc-lint\corpus\acceptance_golden"
OUT = os.path.join(GOLDEN_DIR, "golden_docs.json")
WAIT_S = 180  # 最长等待解析


def api_login():
    body = json.dumps({"username": "boss_admin", "password": "AdminPass123"}).encode()
    req = urllib.request.Request(BASE + "/api/v1/auth/login", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def get_docs(token):
    req = urllib.request.Request(BASE + "/api/v1/documents",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def main():
    token = api_login()
    docs = get_docs(token)
    items = docs if isinstance(docs, list) else docs.get("items", [])
    by_name = {}
    for d in items:
        nm = d.get("filename") or d.get("original_filename") or ""
        by_name[nm] = d
    pdfs = sorted(f for f in os.listdir(GOLDEN_DIR) if f.endswith(".pdf"))
    mapping = {}
    missing = []
    for f in pdfs:
        if f in by_name:
            mapping[f] = str(by_name[f]["id"])
        else:
            missing.append(f)
    print(f"mapped={len(mapping)}/{len(pdfs)} missing={missing}")
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump(mapping, fp, ensure_ascii=False, indent=2)

    # 轮询解析状态
    t0 = time.time()
    while time.time() - t0 < WAIT_S:
        docs = get_docs(token)
        items = docs if isinstance(docs, list) else docs.get("items", [])
        st = {}
        for d in items:
            s = d.get("status", "")
            st[s] = st.get(s, 0) + 1
        print(f"[{int(time.time()-t0)}s] {st}")
        if st.get("parsed", 0) + st.get("failed", 0) == len(pdfs):
            break
        time.sleep(10)
    print("done")


if __name__ == "__main__":
    main()
