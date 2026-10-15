"""W8: 审计日志模型 - 登录/上传/管理操作留痕，独立工具合规基线。"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    # 冗余存用户名：用户被删除后审计仍可追溯
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(48), index=True)
    target: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
