"""首次初始化流程的全新库测试（与其他用例的共享库状态隔离）。"""

from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services.setup_service import ensure_roles
from conftest import TestSessionLocal


def test_setup_blocks_register_until_admin(pristine):
    client = pristine
    assert client.get("/api/v1/setup/status").json()["needs_setup"] is True

    # 管理员未初始化前，注册一律拒绝
    blocked = client.post(
        "/api/v1/auth/register", json={"username": "mem1", "password": "MemberPass123"}
    )
    assert blocked.status_code == 403

    # 初始化管理员
    created = client.post(
        "/api/v1/setup/admin", json={"username": "root", "password": "RootPass123"}
    )
    assert created.status_code == 201, created.text
    assert "admin" in created.json()["roles"]

    status = client.get("/api/v1/setup/status").json()
    assert status["needs_setup"] is False

    # 初始化接口一次性
    again = client.post(
        "/api/v1/setup/admin", json={"username": "root2", "password": "RootPass123"}
    )
    assert again.status_code == 409

    # 初始化完成后，开放注册恢复可用
    ok = client.post(
        "/api/v1/auth/register", json={"username": "mem2", "password": "MemberPass123"}
    )
    assert ok.status_code == 201
    assert ok.json()["roles"] == ["member"]


def test_setup_still_allowed_when_only_member_exists(pristine):
    """回归：直接落库的普通成员不应锁死初始化入口（线上故障场景复现）。"""
    client = pristine
    db = TestSessionLocal()
    try:
        roles = ensure_roles(db)
        member = User(
            username="orphan_member",
            password_hash=hash_password("MemberPass123"),
            is_active=True,
        )
        db.add(member)
        db.flush()
        db.add(UserRole(user_id=member.id, role_id=roles["member"].id))
        db.commit()
    finally:
        db.close()

    assert client.get("/api/v1/setup/status").json()["needs_setup"] is True
    created = client.post(
        "/api/v1/setup/admin", json={"username": "root", "password": "RootPass123"}
    )
    assert created.status_code == 201, created.text
    assert client.get("/api/v1/setup/status").json()["needs_setup"] is False
