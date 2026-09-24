"""100 份合同同时受理浸泡测试：单批 100 个 txt，轮询至整组完成。

在 api 容器内运行：python /tmp/soak100.py
"""
import io
import time

import httpx

BASE = "http://localhost:8000/api/v1"
ADMIN_USER = "boss_admin"
ADMIN_PWD = "AdminPass123"


def login_or_setup():
    r = httpx.post(f"{BASE}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PWD})
    if r.status_code == 200:
        return r.json()["access_token"]
    # 全新首启：初始化管理员后再登录
    r = httpx.post(
        f"{BASE}/setup/admin",
        json={"username": ADMIN_USER, "password": ADMIN_PWD, "confirm_password": ADMIN_PWD},
    )
    r.raise_for_status()
    r = httpx.post(f"{BASE}/auth/login", json={"username": ADMIN_USER, "password": ADMIN_PWD})
    r.raise_for_status()
    return r.json()["access_token"]


def main():
    token = login_or_setup()
    headers = {"Authorization": f"Bearer {token}"}

    files = []
    for i in range(100):
        content = (
            f"第 {i+1} 份测试合同\n甲方：测试公司甲\n乙方：测试公司乙\n"
            "双方就合作事宜达成一致，签订本合同。\n"
        ).encode("utf-8")
        files.append(("files", (f"soak_{i+1:03d}.txt", io.BytesIO(content), "text/plain")))

    t0 = time.time()
    r = httpx.post(f"{BASE}/documents/upload", headers=headers, files=files, timeout=120)
    print("upload:", r.status_code)
    r.raise_for_status()
    out = r.json()
    gid = out["group_id"]
    print("group:", gid, "total:", out["total"])

    while True:
        g = httpx.get(f"{BASE}/task-groups/{gid}", headers=headers, timeout=30).json()
        grp = g["group"]
        if grp.get("finished_at"):
            break
        print(
            f"  pending={grp['pending']} running={grp['running']} "
            f"succeeded={grp['succeeded']} failed={grp['failed']} cancelled={grp['cancelled']}"
        )
        time.sleep(2)

    elapsed = time.time() - t0
    print("---- final ----")
    print(grp)
    print(f"elapsed={elapsed:.1f}s")
    assert grp["succeeded"] == 100, "存在未成功任务"
    print("SOAK OK: 100/100 parsed")


if __name__ == "__main__":
    main()
