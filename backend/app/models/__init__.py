"""导入全部模型，供 Alembic 与 create_all 收集 metadata。"""

from app.db.session import Base
from app.models.document import (
    Artifact,
    CheckFinding,
    Document,
    DocumentTask,
    IntentRoute,
    TaskEvent,
    TaskGroup,
)
from app.models.llm import LLMCallLog
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
    "Document",
    "TaskGroup",
    "DocumentTask",
    "TaskEvent",
    "Artifact",
    "IntentRoute",
    "CheckFinding",
    "LLMCallLog",
]
