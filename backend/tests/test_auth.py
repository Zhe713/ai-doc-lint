"""认证全链路：注册、登录、me、刷新轮换、登出、RBAC、注册开关、登录锁定。"""

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services.setup_service import ensure_roles
from conftest import TestSessionLocal

MEMBER_NAME = "alice_member"
MEMBER_PWD = "MemberPass123"
ADMIN_NAME = "boss_admin"
ADMIN_PWD = "AdminPass123"


def _ensure_admin():
    db = TestSessionLocal()
    try:
        existing = db.scalar(select(User).where(User.username == ADMIN_NAME))
        if existing:
            return
        roles = ensure_roles(db)
        admin = User(
            username=ADMIN_NAME,
            password_hash=hash_password(ADMIN_PWD),
            is_superuser=True,
        )
        db.add(admin)
        db.flush()
        db.add(UserRole(user_id=admin.id, role_id=roles["admin"].id))
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _admin_ready():
    # 新规则下未初始化管理员前禁止注册，因此认证用例统一先保证管理员存在
    _ensure_admin()


def test_register_and_duplicate(client):
    resp = client.post(
        "/api/v1/auth/register", json={"username": MEMBER_NAME, "password": MEMBER_PWD}
    )
    if resp.status_code == 201:
        body = resp.json()
        assert body["username"] == MEMBER_NAME
        assert body["roles"] == ["member"]
    else:
        # 重跑时用户已存在
        assert resp.status_code == 409
    dup = client.post(
        "/api/v1/auth/register", json={"username": MEMBER_NAME, "password": MEMBER_PWD}
    )
    assert dup.status_code == 409


def _login_member(client):
    bad = client.post(
        "/api/v1/auth/login", json={"username": MEMBER_NAME, "password": "wrong-password"}
    )
    assert bad.status_code == 401

    good = client.post(
        "/api/v1/auth/login", json={"username": MEMBER_NAME, "password": MEMBER_PWD}
    )
    assert good.status_code == 200
    tokens = good.json()
    assert tokens["access_token"] and tokens["refresh_token"]
    assert tokens["expires_in"] == 15 * 60
    return tokens


def test_me_requires_token(client):
    assert client.get("/api/v1/users/me").status_code == 401
    tokens = _login_member(client)
    me = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["username"] == MEMBER_NAME


def test_refresh_rotation_and_logout(client):
    tokens = _login_member(client)
    refreshed = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert refreshed.status_code == 200
    new_tokens = refreshed.json()
    assert new_tokens["access_token"] != tokens["access_token"]

    # 旧 refresh token 已随轮换吊销，不能重复使用
    reuse = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert reuse.status_code == 401

    # 登出新会话后，其 refresh 同样失效
    logout = client.post(
        "/api/v1/auth/logout",
        headers={
            "Authorization": f"Bearer {new_tokens['access_token']}",
            "x-refresh-token": new_tokens["refresh_token"],
        },
    )
    assert logout.status_code == 204
    after_logout = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert after_logout.status_code == 401


def test_rbac_admin_only(client):
    _ensure_admin()
    member_tokens = _login_member(client)
    admin_login = client.post(
        "/api/v1/auth/login", json={"username": ADMIN_NAME, "password": ADMIN_PWD}
    )
    assert admin_login.status_code == 200
    admin_tokens = admin_login.json()

    member_forbidden = client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {member_tokens['access_token']}"},
    )
    assert member_forbidden.status_code == 403

    admin_ok = client.get(
        "/api/v1/admin/users",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
    )
    assert admin_ok.status_code == 200
    assert len(admin_ok.json()) >= 2


def test_admin_can_close_registration(client):
    _ensure_admin()
    admin_tokens = client.post(
        "/api/v1/auth/login", json={"username": ADMIN_NAME, "password": ADMIN_PWD}
    ).json()
    closed = client.patch(
        "/api/v1/admin/settings",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
        json={"open_registration": False},
    )
    assert closed.status_code == 200
    assert closed.json()["open_registration"] is False

    blocked = client.post(
        "/api/v1/auth/register", json={"username": "late_member", "password": MEMBER_PWD}
    )
    assert blocked.status_code == 403

    # 恢复开放，避免影响后续
    client.patch(
        "/api/v1/admin/settings",
        headers={"Authorization": f"Bearer {admin_tokens['access_token']}"},
        json={"open_registration": True},
    )


def test_login_lockout_after_failures(client, monkeypatch):
    monkeypatch.setattr("app.services.auth_service.settings.login_max_failures", 3)
    for _ in range(3):
        resp = client.post(
            "/api/v1/auth/login", json={"username": "ghost_user", "password": "nope-12345"}
        )
        assert resp.status_code == 401
    locked = client.post(
        "/api/v1/auth/login", json={"username": "ghost_user", "password": "nope-12345"}
    )
    assert locked.status_code == 429
    monkeypatch.undo()

