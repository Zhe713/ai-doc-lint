"""Day30 验收：文档级相似 + 端到端冒烟。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"


def req(method, path, token=None, body=None):
    r = urllib.request.Request(BASE + path, method=method)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    if body is not None:
        r.data = json.dumps(body).encode()
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read())


def main():
    tok = req("POST", "/auth/login", body={
        "username": "boss_admin", "password": "AdminPass123"})["access_token"]
    out = []

    # 文档级相似：取示范文本（中文长文档）找相似文档
    docs = req("GET", "/documents?limit=5", token=tok)
    dlist = docs if isinstance(docs, list) else (docs.get("items") or docs.get("documents") or [])
    target = None
    for d in dlist:
        if "示范" in d.get("filename", ""):
            target = d
            break
    if target is None and dlist:
        target = dlist[0]
    if target:
        sim = req("GET", f"/documents/{target['id']}/similar?limit=5", token=tok)
        out.append(f"similar-to: {target['filename'][:50]}")
        for h in sim.get("results", []):
            out.append(f"  dist={h.get('distance')}  {h.get('filename','')[:60]}")
    else:
        out.append("no documents found")

    open("/tmp/e2e_report.txt", "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
