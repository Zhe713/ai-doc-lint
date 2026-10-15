"""W7-5: 反馈原因标签 - check_findings.feedback_cause 列

Revision ID: 0010_feedback_cause
Revises: 0009_learning
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_feedback_cause"
down_revision: str | None = "0009_learning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "check_findings",
        sa.Column("feedback_cause", sa.String(length=32), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("check_findings", "feedback_cause")
