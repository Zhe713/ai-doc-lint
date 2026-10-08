"""W5: document_fields / compare_groups / compare_group_documents
+ check_findings.related_document_id（交叉比对）

Revision ID: 0006_cross
Revises: 0005_chat
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_cross"
down_revision: str | None = "0005_chat"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_uuid = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column(
        "check_findings",
        sa.Column("related_document_id", user_uuid,
                  sa.ForeignKey("documents.id", ondelete="SET NULL"),
                  nullable=True),
    )

    op.create_table(
        "document_fields",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("document_id", user_uuid,
                  sa.ForeignKey("documents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("field_key", sa.String(64), nullable=False),
        sa.Column("field_label", sa.String(128), nullable=False),
        sa.Column("value_type", sa.String(16), nullable=False,
                  server_default="string"),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("value_number", sa.Float(), nullable=True),
        sa.Column("value_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False,
                  server_default="1.0"),
        sa.Column("source", sa.String(8), nullable=False,
                  server_default="rule"),
        sa.Column("location", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_document_fields_document",
                    "document_fields", ["document_id"])
    op.create_index("ix_document_fields_doc_key",
                    "document_fields", ["document_id", "field_key"],
                    unique=True)

    op.create_table(
        "compare_groups",
        sa.Column("id", user_uuid, primary_key=True),
        sa.Column("user_id", user_uuid,
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False,
                  server_default="pending"),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()),
                  nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_compare_groups_user",
                    "compare_groups", ["user_id"])

    op.create_table(
        "compare_group_documents",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("compare_group_id", user_uuid,
                  sa.ForeignKey("compare_groups.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("document_id", user_uuid,
                  sa.ForeignKey("documents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("position", sa.Integer(), nullable=False,
                  server_default="0"),
    )
    op.create_index("ix_compare_group_documents_group",
                    "compare_group_documents", ["compare_group_id"])
    op.create_index("ix_compare_group_documents_document",
                    "compare_group_documents", ["document_id"])
    op.create_index("ix_compare_group_doc_unique",
                    "compare_group_documents",
                    ["compare_group_id", "document_id"], unique=True)


def downgrade() -> None:
    op.drop_table("compare_group_documents")
    op.drop_index("ix_compare_groups_user", table_name="compare_groups")
    op.drop_table("compare_groups")
    op.drop_index("ix_document_fields_doc_key", table_name="document_fields")
    op.drop_index("ix_document_fields_document", table_name="document_fields")
    op.drop_table("document_fields")
    op.drop_column("check_findings", "related_document_id")
