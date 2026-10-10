"""Day30 语义检索真实验收：5 组中英查询，核对 Top-K 相关性。"""
import json
import urllib.parse
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


def login():
    return req("POST", "/auth/login", body={
        "username": "boss_admin", "password": "AdminPass123"})


QUERIES = [
    ("zh", "付款条款 预付款 支付方式"),
    ("zh", "违约责任 违约金 赔偿损失"),
    ("en", "termination rights and obligations upon termination"),
    ("zh", "知识产权归属 保密义务 竞业限制"),
    ("en", "governing law and dispute resolution arbitration"),
]


def main():
    tok = login()["access_token"]
    out = []
    for lang, q in QUERIES:
        data = req("GET", f"/search?q={urllib.parse.quote(q)}&limit=5", token=tok)
        out.append(f"\n===== [{lang}] {q} =====")
        for i, hit in enumerate(data.get("results", []), 1):
            out.append(f"  #{i} dist={hit.get('distance')}  {hit.get('filename','')[:60]}")
            out.append(f"      ...{hit.get('content','')[:90]}...")
    open("/tmp/search_report.txt", "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out))


if __name__ == "__main__":
    main()
