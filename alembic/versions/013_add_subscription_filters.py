"""013 - Add hs_codes + countries pre-filter columns to user_subscriptions.

The M5 matching engine previously filtered alerts only by keyword embedding
cosine similarity. The /areas-of-interest UI lets users pick:

  - HS / commodity codes they import
  - Countries they trade with
  - Free-text keywords

Embeddings are great for free-text concepts but wrong for categorical
filters: a user picking "United States" should NOT receive EU-only alerts
just because the embedding fuzzily matches. This migration adds two strict
JSON-array pre-filter columns. An empty list means "no filter" — back-compat
with subscriptions created before this migration.

Revision ID: 013
Revises: 012
Create Date: 2026-05-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_subscriptions",
        sa.Column(
            "hs_codes",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "user_subscriptions",
        sa.Column(
            "countries",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_subscriptions", "countries")
    op.drop_column("user_subscriptions", "hs_codes")
