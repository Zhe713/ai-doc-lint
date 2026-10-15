"""W8: 审计日志表 - audit_logs（登录/上传/管理操作留痕）

Revision ID: 0011_audit_logs
Revises: 0010_feedback_cause
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_audit_logs"
down_revision: str | None = "0010_feedback_cause"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column("target", sa.String(length=128), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_username", "audit_logs", ["username"])
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
