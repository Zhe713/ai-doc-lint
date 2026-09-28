"""W3: check_findings（格式/错别字等校验问题清单）

Revision ID: 0003_check_findings
Revises: 0002_doc_tasks
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_check_findings"
down_revision: str | None = "0002_doc_tasks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_uuid = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "check_findings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_id", user_uuid, sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", user_uuid, sa.ForeignKey("document_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", user_uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checker", sa.String(16), nullable=False),
        sa.Column("rule_id", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(8), server_default="warning", nullable=False),
        sa.Column("location", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("status", sa.String(12), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_check_findings_document", "check_findings", ["document_id"])
    op.create_index("ix_check_findings_user_status", "check_findings", ["user_id", "status"])
    op.create_index("ix_check_findings_task", "check_findings", ["task_id"])
    op.create_index("ix_check_findings_checker_rule", "check_findings", ["checker", "rule_id"])


def downgrade() -> None:
    op.drop_index("ix_check_findings_checker_rule", table_name="check_findings")
    op.drop_index("ix_check_findings_task", table_name="check_findings")
    op.drop_index("ix_check_findings_user_status", table_name="check_findings")
    op.drop_index("ix_check_findings_document", table_name="check_findings")
    op.drop_table("check_findings")
