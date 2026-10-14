"""W7: 自学习闭环 - feedback_reason 列 + learning_logs + learning_suggestions

Revision ID: 0009_learning
Revises: 0008_embed
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_learning"
down_revision: str | None = "0008_embed"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "check_findings",
        sa.Column("feedback_reason", sa.String(length=20), nullable=True),
    )
    op.create_table(
        "learning_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learning_logs_action", "learning_logs", ["action"])
    op.create_index("ix_learning_logs_created", "learning_logs", ["created_at"])
    op.create_table(
        "learning_suggestions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("checker", sa.String(length=16), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, default=0),
        sa.Column("false_count", sa.Integer(), nullable=False, default=0),
        sa.Column("false_rate", sa.Float(), nullable=False, default=0.0),
        sa.Column("status", sa.String(length=12), nullable=False, default="pending"),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_learning_suggestions_status", "learning_suggestions", ["status"])
    op.create_index("ix_learning_suggestions_rule", "learning_suggestions",
                    ["checker", "rule_id"])


def downgrade() -> None:
    op.drop_index("ix_learning_suggestions_rule", table_name="learning_suggestions")
    op.drop_index("ix_learning_suggestions_status", table_name="learning_suggestions")
    op.drop_table("learning_suggestions")
    op.drop_index("ix_learning_logs_created", table_name="learning_logs")
    op.drop_index("ix_learning_logs_action", table_name="learning_logs")
    op.drop_table("learning_logs")
    op.drop_column("check_findings", "feedback_reason")
