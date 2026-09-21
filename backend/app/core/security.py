"""密码哈希（bcrypt）与 JWT 双令牌签发/校验。"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ACCESS_TOKEN = "access"
REFRESH_TOKEN = "refresh"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _encode(token_type: str, subject: str, expires_delta: timedelta, jti: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": jti,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str) -> tuple[str, str]:
    jti = uuid.uuid4().hex
    token = _encode(
        ACCESS_TOKEN, subject, timedelta(minutes=settings.access_token_expire_minutes), jti
    )
    return token, jti


def create_refresh_token(subject: str) -> tuple[str, str]:
    jti = uuid.uuid4().hex
    token = _encode(
        REFRESH_TOKEN, subject, timedelta(days=settings.refresh_token_expire_days), jti
    )
    return token, jti


def decode_token(token: str, expected_type: str) -> dict[str, Any]:
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return payload
