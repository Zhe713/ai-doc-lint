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

TASK_TYPES = ("parse", "review", "annotate", "learn", "cross_compare")
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
ART_ANNOTATED = "annotated"


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


# ---- 校验（review）相关常量（W3） ----

CHECKER_FORMAT = "format"
CHECKER_TYPO = "typo"
CHECKER_CLAUSE = "clause"
CHECKER_CROSS = "cross"
CHECKER_CROSS_DOC = "cross_doc"
CHECKERS = (CHECKER_FORMAT, CHECKER_TYPO, CHECKER_CLAUSE,
            CHECKER_CROSS, CHECKER_CROSS_DOC)
SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"
SEVERITIES = (SEVERITY_ERROR, SEVERITY_WARNING, SEVERITY_INFO)
FINDING_OPEN = "open"
FINDING_IGNORED = "ignored"
FINDING_FIXED = "fixed"
FINDING_STATUSES = (FINDING_OPEN, FINDING_IGNORED, FINDING_FIXED)


class CheckFinding(Base, TimestampMixin):
    """校验发现的问题清单：可筛选、可忽略/标记已修复，是 W7 自动学习的正负例来源。"""

    __tablename__ = "check_findings"
    __table_args__ = (
        Index("ix_check_findings_document", "document_id"),
        Index("ix_check_findings_user_status", "user_id", "status"),
        Index("ix_check_findings_task", "task_id"),
        Index("ix_check_findings_checker_rule", "checker", "rule_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_tasks.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    checker: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False, default=SEVERITY_WARNING)
    # 跨文档比对时关联的另一份文档（checker=cross_doc）
    related_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True,
    )
    # 定位：{page, paragraph_index, start, end, snippet}（不同检查器填各自可用字段）
    location: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default=FINDING_OPEN)
    # W7 反馈采集：false_positive（误报）/ confirmed（确认有效）/ fixed_by_user（已修复）
    feedback_reason: Mapped[str | None] = mapped_column(String(20), nullable=True)


# ---- 字段抽取与交叉比对（W5） ----

# 字段值类型
FIELD_STRING = "string"
FIELD_NUMBER = "number"
FIELD_MONEY = "money"
FIELD_DATE = "date"
FIELD_PERCENT = "percent"
FIELD_TYPES = (FIELD_STRING, FIELD_NUMBER, FIELD_MONEY, FIELD_DATE,
               FIELD_PERCENT)
# 抽取来源
FIELD_SOURCE_RULE = "rule"
FIELD_SOURCE_LLM = "llm"


class DocumentField(Base, TimestampMixin):
    """从文档中抽取出的结构化字段：交叉比对、比对矩阵的数据源。

    规则优先（source=rule，0 token）；规则失败才由 LLM 批量补抽（source=llm）。
    """

    __tablename__ = "document_fields"
    __table_args__ = (
        Index("ix_document_fields_doc_key", "document_id", "field_key",
              unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True,
                                    autoincrement=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    field_label: Mapped[str] = mapped_column(String(128), nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False,
                                           default=FIELD_STRING)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_number: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False,
                                             default=1.0)
    source: Mapped[str] = mapped_column(String(8), nullable=False,
                                        default=FIELD_SOURCE_RULE)
    location: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class CompareGroup(Base, TimestampMixin):
    """文档间比对组：用户勾选多份文档（招标+中标+合同 / 主合同+补充协议）。"""

    __tablename__ = "compare_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True),
                                          primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False,
                                       default=STATUS_PENDING, index=True)
    stats: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)


class CompareGroupDocument(Base):
    """比对组与文档的关联（组内顺序即矩阵列顺序）。"""

    __tablename__ = "compare_group_documents"
    __table_args__ = (
        Index("ix_compare_group_doc_unique", "compare_group_id",
              "document_id", unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True,
                                    autoincrement=True)
    compare_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("compare_groups.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ---- W7 自学习闭环 ----

LEARNING_ACTION_WHITELIST_ADD = "whitelist_add"
LEARNING_ACTION_RULE_SUGGEST = "rule_suggest"
LEARNING_ACTION_SUGGESTION_CONFIRM = "suggestion_confirm"
LEARNING_ACTION_SUGGESTION_REJECT = "suggestion_reject"
LEARNING_ACTION_TUNING = "tuning_run"  # daily / manual
LEARNING_ACTION_REGRESSION = "regression"

SUGGESTION_PENDING = "pending"
SUGGESTION_CONFIRMED = "confirmed"
SUGGESTION_REJECTED = "rejected"


class LearningLog(Base, TimestampMixin):
    """W7 学习闭环操作留痕：每一次自动/手动调优动作都可追溯。"""

    __tablename__ = "learning_logs"
    __table_args__ = (
        Index("ix_learning_logs_action", "action"),
        Index("ix_learning_logs_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    # {rule_id, words, count, reason, trigger, prev/after, ...}
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class LearningSuggestion(Base, TimestampMixin):
    """W7 规则停用建议（人工闸门）：误报率超阈值的规则挂起，管理员确认后停用。"""

    __tablename__ = "learning_suggestions"
    __table_args__ = (
        Index("ix_learning_suggestions_status", "status"),
        Index("ix_learning_suggestions_rule", "checker", "rule_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    checker: Mapped[str] = mapped_column(String(16), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    false_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    false_rate: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(12), nullable=False,
                                        default=SUGGESTION_PENDING)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
