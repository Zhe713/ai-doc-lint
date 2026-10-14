# -*- coding: utf-8 -*-
"""将 golden 集 40 份真实合同上传到系统（登录 boss_admin），输出 doc_id 映射。"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid

BASE = "http://localhost:8080"
GOLDEN_DIR = r"D:\projects\ai-doc-lint\corpus\acceptance_golden"
OUT = os.path.join(GOLDEN_DIR, "golden_docs.json")
CHUNK = 10  # 每批上传份数


def api_login():
    body = json.dumps({"username": "boss_admin", "password": "AdminPass123"}).encode()
    req = urllib.request.Request(
        BASE + "/api/v1/auth/login", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())["access_token"]


def build_multipart(files):
    boundary = "----golden" + uuid.uuid4().hex
    parts = []
    for fp in files:
        with open(fp, "rb") as f:
            data = f.read()
        parts.append(
            (f"--{boundary}\r\n"
             f'Content-Disposition: form-data; name="files"; filename="{os.path.basename(fp)}"\r\n'
             f"Content-Type: application/pdf\r\n\r\n").encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary}"


def upload_batch(token, files):
    body, ctype = build_multipart(files)
    req = urllib.request.Request(
        BASE + "/api/v1/documents/upload", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode())


def main():
    token = api_login()
    print("login ok")
    pdfs = sorted(f for f in os.listdir(GOLDEN_DIR) if f.endswith(".pdf"))
    print(f"pdfs={len(pdfs)}")
    mapping = {}
    for i in range(0, len(pdfs), CHUNK):
        batch = [os.path.join(GOLDEN_DIR, f) for f in pdfs[i:i + CHUNK]]
        resp = upload_batch(token, batch)
        print(f"batch {i // CHUNK + 1}: {resp}")
        items = resp.get("items") or resp.get("documents") or []
        if isinstance(items, dict):
            items = list(items.values())
        for item in items:
            fid = item.get("filename") or item.get("file_name") or ""
            did = str(item.get("id") or item.get("document_id") or "")
            if fid and did:
                mapping[fid] = did
        time.sleep(2)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)
    print(f"mapped={len(mapping)} -> {OUT}")


if __name__ == "__main__":
    main()
