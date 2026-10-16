"""W9: 系统告警事件表 - alert_events

Revision ID: 0012_alerts
Revises: 0011_audit_logs
Create Date: 2026-10-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_alerts"
down_revision: str | None = "0011_audit_logs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alert_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("alert_type", sa.String(length=32), nullable=False),
        sa.Column("message", sa.String(length=512), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_alert_events_alert_type", "alert_events", ["alert_type"])
    op.create_index("ix_alert_events_created_at", "alert_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("alert_events")
