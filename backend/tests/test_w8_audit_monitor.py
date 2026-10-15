"""W8 测试：审计日志留痕与查询、上传魔数校验、系统健康统计、指标端点。"""

import io

from sqlalchemy import select

from app.core.security import hash_password
from app.models.audit import AuditLog
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


def _audit_rows() -> list[AuditLog]:
    db = TestSessionLocal()
    try:
        return list(db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all())
    finally:
        db.close()


# ---------------- 审计留痕 ----------------


def test_login_success_and_fail_audited(client):
    _make_user("w8_aud_login", password="MemberPass123")
    # 成功登录
    ok = client.post("/api/v1/auth/login", json={"username": "w8_aud_login", "password": "MemberPass123"})
    assert ok.status_code == 200
    # 失败登录（错误密码）
    bad = client.post("/api/v1/auth/login", json={"username": "w8_aud_login", "password": "wrong"})
    assert bad.status_code == 401
    rows = _audit_rows()
    actions = [r.action for r in rows]
    assert "login_success" in actions
    assert "login_fail" in actions
    fail_row = next(r for r in rows if r.action == "login_fail")
    # 脱敏：失败审计不记密码
    assert "password" not in str(fail_row.detail or {})


def test_register_audited(client):
    auth = _auth(client, "w8_aud_admin")
    resp = client.post(
        "/api/v1/auth/register",
        json={"username": "w8_aud_new", "password": "NewPass123"},
        headers=auth,
    )
    assert resp.status_code == 201, resp.text
    assert any(r.action == "register" and r.username == "w8_aud_new" for r in _audit_rows())


def test_upload_batch_audited(client):
    headers = _auth(client, "w8_aud_up")
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": ("note.txt", b"hello w8", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert any(r.action == "upload_batch" and (r.detail or {}).get("count") == 1 for r in _audit_rows())


def test_admin_settings_audited(client):
    _make_user("w8_aud_adm", password="MemberPass123", admin=True)
    auth = {"Authorization": f"Bearer {_token(client, 'w8_aud_adm')}"}
    resp = client.patch("/api/v1/admin/settings", json={"open_registration": True}, headers=auth)
    assert resp.status_code == 200, resp.text
    assert any(r.action == "admin_setting" and (r.detail or {}).get("open_registration") is True
               for r in _audit_rows())


def test_audit_logs_api_requires_admin(client):
    member_auth = _auth(client, "w8_aud_usr")
    resp = client.get("/api/v1/admin/audit-logs", headers=member_auth)
    assert resp.status_code == 403
    _make_user("w8_aud_adm2", password="MemberPass123", admin=True)
    admin_auth = {"Authorization": f"Bearer {_token(client, 'w8_aud_adm2')}"}
    ok = client.get("/api/v1/admin/audit-logs?limit=5", headers=admin_auth)
    assert ok.status_code == 200
    body = ok.json()
    assert "total" in body and isinstance(body["items"], list)


# ---------------- 上传魔数校验 ----------------


def test_upload_fake_pdf_rejected(client):
    headers = _auth(client, "w8_magic_pdf")
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": ("fake.pdf", b"this is not a pdf", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 422
    assert "格式不符" in resp.json()["detail"] or "损坏" in resp.json()["detail"]


def test_upload_fake_docx_rejected(client):
    headers = _auth(client, "w8_magic_docx")
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": ("fake.docx", b"not a zip at all", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        headers=headers,
    )
    assert resp.status_code == 422


def test_upload_real_pdf_accepted(client):
    headers = _auth(client, "w8_magic_ok")
    resp = client.post(
        "/api/v1/documents/upload",
        files={"files": ("real.pdf", b"%PDF-1.4 fake minimal content", "application/pdf")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


# ---------------- 系统健康与指标 ----------------


def test_metrics_anonymous(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "aidoc_http_requests_total" in resp.text
    assert "aidoc_celery_queue_depth" in resp.text


def test_system_stats_requires_admin(client):
    member_auth = _auth(client, "w8_sys_usr")
    resp = client.get("/api/v1/admin/system/stats", headers=member_auth)
    assert resp.status_code == 403
    _make_user("w8_sys_adm", password="MemberPass123", admin=True)
    admin_auth = {"Authorization": f"Bearer {_token(client, 'w8_sys_adm')}"}
    ok = client.get("/api/v1/admin/system/stats", headers=admin_auth)
    assert ok.status_code == 200
    body = ok.json()
    assert "documents" in body and "queues" in body and "tasks_by_state" in body
