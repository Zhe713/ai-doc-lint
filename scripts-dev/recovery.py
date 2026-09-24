"""断电恢复验证：
  python /tmp/recovery.py upload   # 上传 10 份后立即退出（不等完成）
  python /tmp/recovery.py check GID
"""
import io
import sys
import time

import httpx

BASE = "http://localhost:8000/api/v1"
ADMIN_USER = "boss_admin"
ADMIN_PWD = "AdminPass123"


def token():
    r = httpx.post(f"{BASE}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PWD})
    r.raise_for_status()
    return r.json()["access_token"]


def upload():
    headers = {"Authorization": f"Bearer {token()}"}
    files = []
    for i in range(10):
        content = f"恢复测试合同 {i+1}\n甲方与乙方达成一致。\n".encode("utf-8")
        files.append(("files", (f"rec_{i+1:02d}.txt", io.BytesIO(content), "text/plain")))
    r = httpx.post(f"{BASE}/documents/upload", headers=headers, files=files, timeout=60)
    r.raise_for_status()
    print(r.json()["group_id"])


def check(gid):
    headers = {"Authorization": f"Bearer {token()}"}
    for _ in range(60):
        g = httpx.get(f"{BASE}/task-groups/{gid}", headers=headers).json()["group"]
        print(g)
        if g.get("finished_at"):
            assert g["succeeded"] == 10, "恢复后有任务未成功"
            print("RECOVERY OK")
            return
        time.sleep(2)
    raise SystemExit("恢复后超时未完成")


if __name__ == "__main__":
    if sys.argv[1] == "upload":
        upload()
    else:
        check(sys.argv[2])
