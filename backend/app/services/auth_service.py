"""注册、登录、令牌刷新与登出。"""

import uuid
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ratelimit import clear_failures, is_locked, record_failure
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import AuthSession, LoginAttempt, User, UserRole
from app.services.setup_service import (
    ROLE_MEMBER,
    ensure_roles,
    is_registration_open,
    needs_setup,
)


class AuthError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def _user_out_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "roles": user.role_names,
        "created_at": user.created_at,
    }


def _issue_tokens(db: Session, user: User, user_agent: str | None, ip: str | None) -> dict:
    access, _ = create_access_token(str(user.id))
    refresh, jti = create_refresh_token(str(user.id))
    session = AuthSession(
        user_id=user.id,
        refresh_jti=jti,
        user_agent=(user_agent or "")[:255] or None,
        ip_address=ip,
        expires_at=datetime.now(timezone.utc)
        + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(session)
    db.commit()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": settings.access_token_expire_minutes * 60,
    }


def register(db: Session, username: str, password: str) -> User:
    if needs_setup(db):
        raise AuthError("setup_required", "系统尚未初始化管理员，请先完成初始化", 403)
    if not is_registration_open(db):
        raise AuthError("registration_closed", "管理员已关闭开放注册", 403)
    username = username.strip()
    if db.scalar(select(User).where(User.username == username)):
        raise AuthError("username_taken", "用户名已被占用", 409)
    roles = ensure_roles(db)
    user = User(username=username, password_hash=hash_password(password), is_active=True)
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=roles[ROLE_MEMBER].id))
    db.commit()
    db.refresh(user)
    return user


def _record_attempt(db: Session, username: str, ip: str, success: bool, reason: str | None) -> None:
    db.add(LoginAttempt(username=username[:64], ip_address=ip, success=success, reason=reason))
    db.commit()


def login(
    db: Session, username: str, password: str, user_agent: str | None, ip: str | None
) -> dict:
    username = username.strip()
    if is_locked(username, ip or "-"):
        _record_attempt(db, username, ip, False, "locked")
        raise AuthError(
            "temporarily_locked",
            f"失败次数过多，账户已临时锁定 {settings.login_lock_seconds // 60} 分钟",
            429,
        )
    user = db.scalar(select(User).where(User.username == username))
    if user is None or not verify_password(password, user.password_hash):
        failures = record_failure(username, ip or "-")
        _record_attempt(db, username, ip, False, "bad_credentials")
        remaining = max(settings.login_max_failures - failures, 0) if failures else None
        msg = "用户名或密码错误"
        if remaining is not None and remaining > 0:
            msg += f"，再失败 {remaining} 次将临时锁定"
        raise AuthError("bad_credentials", msg, 401)
    if not user.is_active:
        _record_attempt(db, username, ip, False, "inactive")
        raise AuthError("inactive", "账户已被停用", 403)
    clear_failures(username, ip or "-")
    _record_attempt(db, username, ip, True, None)
    return _issue_tokens(db, user, user_agent, ip)


def refresh_tokens(db: Session, refresh_token: str) -> dict:
    try:
        payload = decode_token(refresh_token, "refresh")
    except jwt.PyJWTError as exc:
        raise AuthError("invalid_token", "refresh token 无效或已过期", 401) from exc
    jti = payload.get("jti")
    session = db.scalar(select(AuthSession).where(AuthSession.refresh_jti == jti))
    if session is None or session.revoked_at is not None:
        raise AuthError("session_revoked", "登录会话已登出，请重新登录", 401)
    if session.expires_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc):
        raise AuthError("session_expired", "登录已过期，请重新登录", 401)
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise AuthError("inactive", "账户不可用", 403)
    # 轮换：吊销旧会话，签发新令牌
    session.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return _issue_tokens(db, user, session.user_agent, session.ip_address)


def logout(db: Session, refresh_token: str | None) -> None:
    if not refresh_token:
        return
    try:
        payload = decode_token(refresh_token, "refresh")
    except jwt.PyJWTError:
        return
    session = db.scalar(
        select(AuthSession).where(AuthSession.refresh_jti == payload.get("jti"))
    )
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()


def user_public(user: User) -> dict:
    return _user_out_dict(user)
