"""W4: llm_call_logs（LLM 调用用量与稳定性审计）

Revision ID: 0004_llm_call_logs
Revises: 0003_check_findings
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_llm_call_logs"
down_revision: str | None = "0003_check_findings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_uuid = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "llm_call_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("user_id", user_uuid,
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("scene", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False, server_default="primary"),
        sa.Column("model", sa.String(64), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_llm_call_logs_created", "llm_call_logs", ["created_at"])
    op.create_index("ix_llm_call_logs_scene", "llm_call_logs", ["scene", "success"])


def downgrade() -> None:
    op.drop_index("ix_llm_call_logs_scene", table_name="llm_call_logs")
    op.drop_index("ix_llm_call_logs_created", table_name="llm_call_logs")
    op.drop_table("llm_call_logs")
