"""W9-2: 系统告警事件表 - alert_events（队列积压/解析失败率/任务卡死超阈值）。"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

ALERT_WARNING = "warning"
ALERT_CRITICAL = "critical"
ALERT_STATUS_ACTIVE = "active"
ALERT_STATUS_RESOLVED = "resolved"


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False, default=ALERT_WARNING)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ALERT_STATUS_ACTIVE)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
