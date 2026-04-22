"""005 - Add artifact_uri to raw_documents

Stores the S3 URI (or other object-store URI) where the extracted text
for each RawDocument has been archived. Nullable so rows created before
artifact storage was wired — or rows written when AWS_S3_BUCKET is not
configured — remain valid.

Revision ID: 005
Revises: 004
Create Date: 2026-04-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_documents",
        sa.Column("artifact_uri", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "source_versions",
        sa.Column("artifact_uri", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_versions", "artifact_uri")
    op.drop_column("raw_documents", "artifact_uri")
