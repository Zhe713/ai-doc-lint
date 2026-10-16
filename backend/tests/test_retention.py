"""W9-1: 数据保留自动清理测试 - 过期文档删除、未过期保留、0 天数跳过、审计留痕。"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.document import Document, DocumentTask
from app.models.user import User, UserRole
from app.services.setup_service import (
    SETTING_DATA_RETENTION,
    set_setting,
)
from conftest import TestSessionLocal


def _make_user(username: str):
    db = TestSessionLocal()
    try:
        from app.services.setup_service import ensure_roles

        roles = ensure_roles(db)
        user = User(username=username, password_hash=hash_password("MemberPass123"))
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=roles["member"].id))
        db.commit()
    finally:
        db.close()


def _make_doc(db, user_id: uuid.UUID, filename: str, days_ago: int) -> Document:
    doc = Document(
        user_id=user_id,
        filename=filename,
        storage_key=f"docs/{user_id}/{uuid.uuid4().hex}/{filename}",
        sha256=uuid.uuid4().hex,
        size_bytes=10,
        content_type="text/plain",
        ext="txt",
        doc_type="auto",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
    )
    db.add(doc)
    db.flush()
    return doc


def test_cleanup_deletes_only_expired(client):
    db = TestSessionLocal()
    try:
        _make_user("retention_u1")
        user = db.execute(select(User).where(User.username == "retention_u1")).scalar_one()
        old = _make_doc(db, user.id, "old.txt", days_ago=30)
        recent = _make_doc(db, user.id, "recent.txt", days_ago=0)
        set_setting(db, SETTING_DATA_RETENTION, 7)
        db.commit()
        old_id, recent_id = old.id, recent.id
    finally:
        db.close()

    from app.tasks import retention as retention_mod
    from app.tasks.retention import cleanup_expired_documents

    # 任务模块默认 SessionLocal 指向 dev 库，替换为测试库
    retention_mod.SessionLocal = TestSessionLocal
    result = cleanup_expired_documents()

    db = TestSessionLocal()
    try:
        assert result["enabled"] is True
        assert result["deleted"] == 1
        assert db.get(Document, old_id) is None
        assert db.get(Document, recent_id) is not None
        # 关联任务级联删除
        assert db.execute(
            select(DocumentTask).where(DocumentTask.document_id == old_id)
        ).scalars().first() is None
        # 审计留痕
        audit = db.execute(
            select(AuditLog).where(AuditLog.action == "retention_cleanup")
        ).scalars().all()
        assert len(audit) >= 1
        assert audit[-1].detail["deleted"] == 1
    finally:
        db.close()


def test_cleanup_disabled_when_zero(client):
    db = TestSessionLocal()
    try:
        _make_user("retention_u2")
        user = db.execute(select(User).where(User.username == "retention_u2")).scalar_one()
        _make_doc(db, user.id, "keep.txt", days_ago=99)
        set_setting(db, SETTING_DATA_RETENTION, 0)
        db.commit()
    finally:
        db.close()

    from app.tasks import retention as retention_mod
    from app.tasks.retention import cleanup_expired_documents

    retention_mod.SessionLocal = TestSessionLocal
    result = cleanup_expired_documents()
    assert result["enabled"] is False
    assert result["deleted"] == 0

    db = TestSessionLocal()
    try:
        assert db.execute(select(Document)).scalars().all()  # 仍有文档
    finally:
        db.close()
