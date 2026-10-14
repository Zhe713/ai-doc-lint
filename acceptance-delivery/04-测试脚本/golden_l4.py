# -*- coding: utf-8 -*-
"""L4 容错与稳定性测试（API 级）。

用例：
  T1 损坏 PDF（内容非 PDF 结构）-> 应拒收或任务 failed 带 error_message
  T2 非法扩展名（.zip）-> 应 400 拒收
  T3 空文件（.txt 0 字节）-> 应 400 拒收
  T4 新注册普通用户 -> 文档列表为空（权限隔离）
  T5 普通用户越权访问他人文档 -> 404
"""
import io
import json
import os
import tempfile
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8080"
OUT = []
DOCS_API = "/api/v1/documents"


def call(method, path, token=None, body=None, ctype="application/json", timeout=60):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = ctype
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


def login(u, p):
    st, txt = call("POST", "/api/v1/auth/login", body=json.dumps(
        {"username": u, "password": p}).encode())
    if st != 200:
        raise RuntimeError(f"login failed {st}: {txt}")
    return json.loads(txt)["access_token"]


def upload(token, filename, data, doc_type="contract", checks="format,typo"):
    boundary = "----l4boundary"
    parts = []
    meta = {"doc_type": doc_type, "checks": checks}
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="meta"\r\n\r\n{json.dumps(meta)}')
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n')
    body = ("\r\n".join(parts)).encode() + data + f"\r\n--{boundary}--\r\n".encode()
    return call("POST", "/api/v1/documents/upload", token=token, body=body,
                ctype=f"multipart/form-data; boundary={boundary}", timeout=120)


def register(u, p):
    st, txt = call("POST", "/api/v1/auth/register", body=json.dumps(
        {"username": u, "password": p, "role": "user"}).encode())
    return st, txt


def main():
    admin = login("boss_admin", "AdminPass123")

    # T1 损坏 PDF
    bad_pdf = b"this is not a real pdf file, just some random bytes " * 200
    st, txt = upload(admin, "broken_test.pdf", bad_pdf)
    OUT.append(("T1 损坏PDF", st, txt[:200]))

    # T2 非法扩展名
    st, txt = upload(admin, "evil.zip", b"PK\x03\x04 fake zip bytes")
    OUT.append(("T2 非法扩展名zip", st, txt[:200]))

    # T3 空文件
    st, txt = upload(admin, "empty_test.txt", b"")
    OUT.append(("T3 空文件", st, txt[:200]))

    # T4/T5 权限隔离
    uname = f"l4user_{int(time.time())}"
    st, txt = register(uname, "Pass1234")
    OUT.append(("T4 注册新用户", st, txt[:120]))
    try:
        u_token = login(uname, "Pass1234")
        st, txt = call("GET", DOCS_API, token=u_token)
        docs = json.loads(txt) if st == 200 else {}
        total = docs.get("total", len(docs.get("items", [])) if isinstance(docs, dict) else "?")
        OUT.append(("T4 新用户文档列表", st, f"total={total}"))
        # 越权访问 boss 文档
        st, txt = call("GET", "/api/v1/documents/61bd7924-7323-40c6-8b9d-dc42cce2452b", token=u_token)
        OUT.append(("T5 越权访问他人文档", st, txt[:150]))
    except Exception as e:  # noqa: BLE001
        OUT.append(("T4/T5", -1, str(e)[:200]))

    for row in OUT:
        print(" | ".join(str(x) for x in row))


if __name__ == "__main__":
    main()
