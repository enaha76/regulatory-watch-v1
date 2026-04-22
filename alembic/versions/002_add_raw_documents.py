"""002 - Add raw_documents table for ingestion layer

Revision ID: 002
Revises: 001
Create Date: 2026-03-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "raw_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("content_hash", name="uq_raw_document_content_hash"),
        sa.CheckConstraint(
            "source_type IN ('web','pdf','rss','xml','email')",
            name="ck_raw_document_source_type",
        ),
    )
    op.create_index("ix_raw_documents_source_type", "raw_documents", ["source_type"])
    op.create_index("ix_raw_documents_fetched_at", "raw_documents", ["fetched_at"])
    op.create_index("ix_raw_documents_content_hash", "raw_documents", ["content_hash"])


def downgrade() -> None:
    op.drop_table("raw_documents")
