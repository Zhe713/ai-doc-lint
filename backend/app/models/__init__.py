"""导入全部模型，供 Alembic 与 create_all 收集 metadata。"""

from app.db.session import Base
from app.models.user import (
    AuthSession,
    LoginAttempt,
    Role,
    SystemSetting,
    User,
    UserRole,
)

__all__ = [
    "Base",
    "Role",
    "User",
    "UserRole",
    "AuthSession",
    "LoginAttempt",
    "SystemSetting",
]
