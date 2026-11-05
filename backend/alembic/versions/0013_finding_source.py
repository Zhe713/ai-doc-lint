"""问题来源与 LLM 判定依据 - check_findings 增加 source/llm_reason/llm_model

Revision ID: 0013_finding_source
Revises: 0012_alerts
Create Date: 2026-11-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_finding_source"
down_revision: str | None = "0012_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "check_findings",
        sa.Column(
            "source", sa.String(length=8), nullable=False,
            server_default="rule",
        ),
    )
    op.add_column(
        "check_findings",
        sa.Column("llm_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "check_findings",
        sa.Column("llm_model", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_check_findings_source", "check_findings", ["source"]
    )


def downgrade() -> None:
    op.drop_index("ix_check_findings_source", table_name="check_findings")
    op.drop_column("check_findings", "llm_model")
    op.drop_column("check_findings", "llm_reason")
    op.drop_column("check_findings", "source")
