"""W2 批量解析相关表：文档、任务组、文档任务、任务事件、产物、意图路由（预留）。

状态用字符串常量而非 PG enum，后续新增状态无需迁移类型。
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


# ---- 任务状态机常量（见 services/task_state.py 的合法跳转表） ----

TASK_TYPES = ("parse", "review", "annotate", "learn")
# parse=本周期；review/annotate/learn 仅定义队列与类型，W4/W7 才会入任务
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_RETRYING = "retrying"
STATUS_AWAITING = "awaiting_decision"
STATUS_PARSED = "parsed"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"
TASK_STATUSES = (
    STATUS_PENDING,
    STATUS_RUNNING,
    STATUS_RETRYING,
    STATUS_AWAITING,
    STATUS_PARSED,
    STATUS_FAILED,
    STATUS_CANCELLED,
)
TERMINAL_STATUSES = (STATUS_PARSED, STATUS_FAILED, STATUS_CANCELLED)

# 闸门三选一
GATE_RETRY_OCR = "retry_ocr"
GATE_CONTINUE_WARNINGS = "continue_with_warnings"
GATE_CANCEL = "cancel"
GATE_DECISIONS = (GATE_RETRY_OCR, GATE_CONTINUE_WARNINGS, GATE_CANCEL)

# 闸门原因
GATE_OCR_REQUIRED = "ocr_required"
GATE_PARSE_FAILED = "parse_failed"
GATE_LOW_CONFIDENCE = "low_confidence"
GATE_UNSUPPORTED = "unsupported"

# 产物类型
ART_ORIGINAL = "original"
ART_NORMALIZED_JSON = "normalized_json"
ART_PLAINTEXT = "plaintext"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ext: Mapped[str] = mapped_column(String(16), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_PENDING)


class TaskGroup(Base, TimestampMixin):
    """一次批量上传 = 一个任务组，组内各状态计数用于进度看板。"""

    __tablename__ = "task_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    awaiting: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancelled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DocumentTask(Base, TimestampMixin):
    __tablename__ = "document_tasks"
    __table_args__ = (
        Index("ix_doc_tasks_user_status", "user_id", "status"),
        Index("ix_doc_tasks_group", "group_id"),
        Index("ix_doc_tasks_celery", "celery_task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_groups.id", ondelete="SET NULL"), nullable=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(16), nullable=False, default="parse")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=STATUS_PENDING, index=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)

    gate_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gate_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    result_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskEvent(Base):
    """只追加的进度/审计事件流（时间线、卡死判定、调试依据）。"""

    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class Artifact(Base):
    """解析产物索引：原件 / normalized.json / plaintext.txt / OCR 中间件。"""

    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_tasks.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class IntentRoute(Base):
    """三层意图漏斗路由审计（W2 仅建表；W3 起由 router 内核写入，W7 学习闭环读取）。"""

    __tablename__ = "intent_routes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)  # assistant / pipeline
    final_layer: Mapped[str] = mapped_column(String(8), nullable=False)  # rule / context / llm
    path: Mapped[str | None] = mapped_column(String(128), nullable=True)
    intent_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    slots: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    clarified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tool_calls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback: Mapped[int | None] = mapped_column(Integer, nullable=True)  # +1 / -1
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
