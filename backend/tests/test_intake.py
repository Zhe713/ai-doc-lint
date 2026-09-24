"""上传受理校验：鉴权、扩展名、批量上限、归属隔离。"""

import io

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services.setup_service import ensure_roles
from conftest import TestSessionLocal


def _make_user(username: str, password: str = "MemberPass123", admin: bool = False):
    db = TestSessionLocal()
    try:
        roles = ensure_roles(db)
        user = User(username=username, password_hash=hash_password(password), is_superuser=admin)
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=roles["admin" if admin else "member"].id))
        db.commit()
    finally:
        db.close()


def _token(client, username: str, password: str = "MemberPass123") -> str:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _auth(client, username: str):
    _make_user(username)
    return {"Authorization": f"Bearer {_token(client, username)}"}


def test_upload_requires_auth(client):
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": ("a.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 401


def test_doc_legacy_rejected(client):
    headers = _auth(client, "intake_doc")
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": ("old.doc", b"fake", "application/msword")},
        headers=headers,
    )
    assert resp.status_code == 422
    assert ".docx" in resp.json()["detail"]


def test_unsupported_extension_rejected(client):
    headers = _auth(client, "intake_exe")
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": ("evil.exe", b"MZ", "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 422


def test_valid_txt_accepted_and_enqueued(client):
    headers = _auth(client, "intake_ok")
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": ("hello.txt", b"hello world", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["tasks"][0]["status"] == "pending"
    assert body["tasks"][0]["filename"] == "hello.txt"

    # 组列表与明细可查
    groups = client.get("/api/v1/task-groups", headers=headers).json()
    assert any(g["id"] == body["group_id"] for g in groups)
    detail = client.get(f"/api/v1/task-groups/{body['group_id']}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["tasks"]) == 1


def test_batch_over_limit_rejected(client):
    headers = _auth(client, "intake_many")
    files = [("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(101)]
    resp = client.post("/api/v1/documents/upload", files=files, headers=headers)
    assert resp.status_code == 422
    assert "100" in resp.json()["detail"]


def test_group_isolation_between_users(client):
    h1 = _auth(client, "owner_a")
    up = client.post(
        "/api/v1/documents/upload",
        files={"files": ("a.txt", b"aaa", "text/plain")},
        headers=h1,
    ).json()
    h2 = _auth(client, "owner_b")
    resp = client.get(f"/api/v1/task-groups/{up['group_id']}", headers=h2)
    assert resp.status_code == 404
