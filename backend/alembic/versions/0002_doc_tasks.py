"""W2: documents / task_groups / document_tasks / task_events / artifacts / intent_routes

Revision ID: 0002_doc_tasks
Revises: 0001_initial
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_doc_tasks"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_uuid = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", user_uuid, primary_key=True),
        sa.Column("user_id", user_uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("ext", sa.String(16), nullable=False),
        sa.Column("doc_type", sa.String(32), server_default="unknown", nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])
    op.create_index("ix_documents_sha256", "documents", ["sha256"])

    op.create_table(
        "task_groups",
        sa.Column("id", user_uuid, primary_key=True),
        sa.Column("user_id", user_uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pending", sa.Integer(), server_default="0", nullable=False),
        sa.Column("running", sa.Integer(), server_default="0", nullable=False),
        sa.Column("succeeded", sa.Integer(), server_default="0", nullable=False),
        sa.Column("awaiting", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancelled", sa.Integer(), server_default="0", nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_task_groups_user_id", "task_groups", ["user_id"])

    op.create_table(
        "document_tasks",
        sa.Column("id", user_uuid, primary_key=True),
        sa.Column("group_id", user_uuid, sa.ForeignKey("task_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("document_id", user_uuid, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", user_uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_type", sa.String(16), server_default="parse", nullable=False),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("celery_task_id", sa.String(64), nullable=True),
        sa.Column("priority", sa.Integer(), server_default="5", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="2", nullable=False),
        sa.Column("gate_reason", sa.String(64), nullable=True),
        sa.Column("gate_payload", postgresql.JSONB(), nullable=True),
        sa.Column("warnings", postgresql.JSONB(), nullable=True),
        sa.Column("result_refs", postgresql.JSONB(), nullable=True),
        sa.Column("stats", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_doc_tasks_user_status", "document_tasks", ["user_id", "status"])
    op.create_index("ix_doc_tasks_group", "document_tasks", ["group_id"])
    op.create_index("ix_doc_tasks_celery", "document_tasks", ["celery_task_id"])
    op.create_index("ix_doc_tasks_status", "document_tasks", ["status"])

    op.create_table(
        "task_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_id", user_uuid, sa.ForeignKey("document_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("message", sa.String(255), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_task_events_task_id", "task_events", ["task_id"])
    op.create_index("ix_task_events_created_at", "task_events", ["created_at"])

    op.create_table(
        "artifacts",
        sa.Column("id", user_uuid, primary_key=True),
        sa.Column("document_id", user_uuid, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", user_uuid, sa.ForeignKey("document_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_artifacts_document_id", "artifacts", ["document_id"])

    op.create_table(
        "intent_routes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", user_uuid, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=True),
        sa.Column("domain", sa.String(16), nullable=False),
        sa.Column("final_layer", sa.String(8), nullable=False),
        sa.Column("path", sa.String(128), nullable=True),
        sa.Column("intent_code", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("slots", postgresql.JSONB(), nullable=True),
        sa.Column("clarified", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("feedback", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_intent_routes_user_id", "intent_routes", ["user_id"])
    op.create_index("ix_intent_routes_session_id", "intent_routes", ["session_id"])
    op.create_index("ix_intent_routes_intent_code", "intent_routes", ["intent_code"])
    op.create_index("ix_intent_routes_created_at", "intent_routes", ["created_at"])


def downgrade() -> None:
    op.drop_table("intent_routes")
    op.drop_table("artifacts")
    op.drop_table("task_events")
    op.drop_table("document_tasks")
    op.drop_table("task_groups")
    op.drop_table("documents")
