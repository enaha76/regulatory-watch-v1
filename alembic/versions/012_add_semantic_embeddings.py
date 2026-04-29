"""012 - Add semantic embeddings for M5 subscription matching.

Replaces the tsquery / metadata-filter approach on user_subscriptions
with a single vector embedding per subscription:

  user_subscriptions:
    - DROP  keyword_query, topics, origin_countries, destination_countries
    - ADD   keywords (JSON array of raw keyword strings)
    - ADD   similarity_threshold (float, default 0.72)
    - ADD   embedding vector(1536)

  change_events:
    - ADD   embedding vector(1536)  — populated after L3 scoring

Requires the pgvector Postgres extension (bundled in pgvector Docker
image or installable via `CREATE EXTENSION vector`).

Revision ID: 012
Revises: 011
Create Date: 2026-04-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension (idempotent).
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── user_subscriptions: drop old filter columns + indexes ────────
    # GIN indexes must be dropped before their columns.
    op.drop_index("ix_user_subscriptions_topics",
                  table_name="user_subscriptions", if_exists=True)
    op.drop_index("ix_user_subscriptions_origin_countries",
                  table_name="user_subscriptions", if_exists=True)
    op.drop_index("ix_user_subscriptions_destination_countries",
                  table_name="user_subscriptions", if_exists=True)

    op.drop_column("user_subscriptions", "keyword_query")
    op.drop_column("user_subscriptions", "topics")
    op.drop_column("user_subscriptions", "origin_countries")
    op.drop_column("user_subscriptions", "destination_countries")

    # ── user_subscriptions: add new semantic columns ─────────────────
    op.add_column(
        "user_subscriptions",
        sa.Column("keywords", sa.JSON(), nullable=False,
                  server_default="[]"),
    )
    op.add_column(
        "user_subscriptions",
        sa.Column("similarity_threshold", sa.Float(), nullable=False,
                  server_default="0.72"),
    )
    # vector(1536) via raw DDL — avoids a pgvector Python import at
    # migration time (the extension only needs to exist in Postgres).
    op.execute(
        "ALTER TABLE user_subscriptions "
        "ADD COLUMN embedding vector(1536)"
    )

    # ── change_events: add embedding column ──────────────────────────
    op.execute(
        "ALTER TABLE change_events "
        "ADD COLUMN embedding vector(1536)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE change_events DROP COLUMN IF EXISTS embedding")
    op.execute(
        "ALTER TABLE user_subscriptions DROP COLUMN IF EXISTS embedding"
    )
    op.drop_column("user_subscriptions", "similarity_threshold")
    op.drop_column("user_subscriptions", "keywords")

    # Restore old columns (nullable so existing rows are not broken).
    op.add_column(
        "user_subscriptions",
        sa.Column("keyword_query", sa.Text(), nullable=True),
    )
    op.add_column(
        "user_subscriptions",
        sa.Column("topics", sa.ARRAY(sa.String(length=40)), nullable=True),
    )
    op.add_column(
        "user_subscriptions",
        sa.Column("origin_countries",
                  sa.ARRAY(sa.String(length=8)), nullable=True),
    )
    op.add_column(
        "user_subscriptions",
        sa.Column("destination_countries",
                  sa.ARRAY(sa.String(length=8)), nullable=True),
    )
    op.create_index("ix_user_subscriptions_topics",
                    "user_subscriptions", ["topics"],
                    postgresql_using="gin")
    op.create_index("ix_user_subscriptions_origin_countries",
                    "user_subscriptions", ["origin_countries"],
                    postgresql_using="gin")
    op.create_index("ix_user_subscriptions_destination_countries",
                    "user_subscriptions", ["destination_countries"],
                    postgresql_using="gin")
