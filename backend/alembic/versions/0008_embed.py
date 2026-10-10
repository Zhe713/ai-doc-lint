"""W6: document_chunks + pgvector 扩展（语义检索向量化）

Revision ID: 0008_embed
Revises: 0007_rules
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0008_embed"
down_revision: str | None = "0007_rules"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

user_uuid = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("document_id", user_uuid,
                  sa.ForeignKey("documents.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_chunks_document", "document_chunks", ["document_id"])
    op.create_index("ix_chunks_doc_idx", "document_chunks",
                    ["document_id", "chunk_index"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_chunks_doc_idx", table_name="document_chunks")
    op.drop_index("ix_chunks_document", table_name="document_chunks")
    op.drop_table("document_chunks")
