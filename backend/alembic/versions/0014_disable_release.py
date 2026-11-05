"""规则级停用覆盖 + 文档放行记录

Revision ID: 0014_disable_release
Revises: 0013_finding_source
Create Date: 2026-11-05

- disabled_rules：单条规则停用（内置规则无实体可改，只能靠覆盖表生效）
- document_releases：「放行」落库，从界面徽标变成可查询事实
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014_disable_release"
down_revision: str | None = "0013_finding_source"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "disabled_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("pack_type", sa.String(length=16), nullable=False),
        sa.Column("rule_id", sa.String(length=96), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("pack_type", "rule_id", "user_id",
                            name="uq_disabled_rule_scoped"),
    )
    op.create_index("ix_disabled_rules_user_id", "disabled_rules", ["user_id"])
    op.create_index("ix_disabled_rules_scope", "disabled_rules",
                    ["pack_type", "user_id"])
    # PG 的 UNIQUE 把 NULL 视为互不相等，全局停用（user_id IS NULL）需要部分唯一索引
    op.execute(
        "CREATE UNIQUE INDEX uq_disabled_rule_global "
        "ON disabled_rules (pack_type, rule_id) WHERE user_id IS NULL"
    )

    op.create_table(
        "document_releases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("baseline_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("changed_ratio", sa.Float(), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_document_releases_document_id", "document_releases",
                    ["document_id"])
    op.create_index("ix_document_releases_user_id", "document_releases",
                    ["user_id"])
    op.create_index("ix_document_releases_doc", "document_releases",
                    ["document_id", "created_at"])


def downgrade() -> None:
    op.drop_table("document_releases")
    op.drop_index("uq_disabled_rule_global", table_name="disabled_rules")
    op.drop_table("disabled_rules")
