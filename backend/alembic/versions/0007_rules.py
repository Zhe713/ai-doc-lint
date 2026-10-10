"""W6: rule_packs（自定义规则包：格式/条款/字段/勾稽）

Revision ID: 0007_rules
Revises: 0006_cross
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_rules"
down_revision: str | None = "0006_cross"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_uuid = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "rule_packs",
        sa.Column("id", user_uuid, primary_key=True),
        sa.Column("user_id", user_uuid, nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("pack_type", sa.String(16), nullable=False),
        sa.Column("doc_type", sa.String(32), nullable=False,
                  server_default="global"),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False,
                  server_default="1"),
        sa.Column("yaml_content", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False,
                  server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_rule_packs_user", "rule_packs", ["user_id"])
    op.create_index("ix_rule_packs_type_doc",
                    "rule_packs", ["pack_type", "doc_type", "enabled"])


def downgrade() -> None:
    op.drop_index("ix_rule_packs_type_doc", table_name="rule_packs")
    op.drop_index("ix_rule_packs_user", table_name="rule_packs")
    op.drop_table("rule_packs")
