"""020 - HNSW indexes on embeddings + b-tree on alerts hot path.

Audit found four index gaps on the hot path:

  1. ``change_events.embedding``     — sequential scan during matching
  2. ``user_subscriptions.embedding`` — sequential scan during matching
  3. ``alerts.created_at``            — inbox list orders by it (ORDER BY DESC)
  4. ``alerts.status``                — status filter on every list call

The two vector columns get HNSW indexes (pgvector ≥ 0.5, cosine ops).
HNSW is the right pick over IVFFlat for our access pattern: small
candidate sets per query (one event vs ~N subscriptions, or one
subscription vs ~N events), unpredictable query distribution, and we
don't have enough data yet to train good IVFFlat clusters.

HNSW parameters: defaults (m=16, ef_construction=64). Defaults are
well-tuned for ~10K–10M rows and our cosine workload — tightening
helps recall on niche datasets but isn't worth the build time at
this scale.

Revision ID: 020
Revises: 019
Create Date: 2026-05-07
"""
from typing import Sequence, Union

from alembic import op


revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── HNSW on change_events.embedding (cosine) ────────────────────
    # Built CONCURRENTLY so a populated table doesn't block writes
    # during the build. Wrapped in autocommit because CREATE INDEX
    # CONCURRENTLY can't run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_change_events_embedding_hnsw "
            "ON public.change_events USING hnsw "
            "(embedding vector_cosine_ops) "
            "WHERE embedding IS NOT NULL"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_user_subscriptions_embedding_hnsw "
            "ON public.user_subscriptions USING hnsw "
            "(embedding vector_cosine_ops) "
            "WHERE embedding IS NOT NULL AND is_active = TRUE"
        )

        # ── alerts hot-path b-trees ────────────────────────────────
        # `created_at DESC` is the inbox ordering. Plain b-tree with
        # ASC works just as well for ORDER BY DESC scans (Postgres
        # walks the index backward), so no need for a DESC-specific
        # opclass.
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_alerts_created_at "
            "ON public.alerts USING btree (created_at)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_alerts_status "
            "ON public.alerts USING btree (status)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_alerts_status")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_alerts_created_at")
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "ix_user_subscriptions_embedding_hnsw"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "ix_change_events_embedding_hnsw"
        )
