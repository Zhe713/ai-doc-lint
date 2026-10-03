"""W4: chat_sessions / chat_messages（报告页对话助手）

Revision ID: 0005_chat
Revises: 0004_llm_call_logs
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_chat"
down_revision: str | None = "0004_llm_call_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_uuid = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "chat_sessions",
        sa.Column("id", user_uuid, primary_key=True),
        sa.Column("user_id", user_uuid,
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", user_uuid,
                  sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=True),
        sa.Column("title", sa.String(128), nullable=False, server_default="新对话"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_sessions_user", "chat_sessions", ["user_id"])

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", user_uuid,
                  sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("route_layer", sa.String(16), nullable=True),
        sa.Column("intent", sa.String(64), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chat_messages_session", "chat_messages", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_user", table_name="chat_sessions")
    op.drop_table("chat_sessions")
