"""003 - Add page_count + pages offsets to raw_documents

Adds two nullable columns so PDFs (and other multi-part source types)
can be stored as a single row with per-page character offsets into
raw_text, instead of one row per page.

Revision ID: 003
Revises: 002
Create Date: 2026-04-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_documents",
        sa.Column("page_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "raw_documents",
        sa.Column("pages", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("raw_documents", "pages")
    op.drop_column("raw_documents", "page_count")
