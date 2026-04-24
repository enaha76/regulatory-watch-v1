"""012 - Composite index on source_versions for latest-by-URL lookup.

Change detection runs this query on every batch of ingested documents
(via `_prefetch_version_state` in `app.services.change_detection`):

    SELECT DISTINCT ON (source_url) *
    FROM source_versions
    WHERE source_url = ANY(:urls)
    ORDER BY source_url, last_seen_at DESC

With only the PK and UNIQUE(source_url, content_hash) indexes, Postgres
heap-scans matching rows and sorts by `last_seen_at`. As the version
history grows (each frequently-crawled URL accumulates hundreds of
SourceVersion rows over months), this becomes a latency cliff on
ingestion throughput.

The composite index `(source_url, last_seen_at DESC)` lets Postgres
short-circuit to an O(log n) index-only lookup — the latest version
per URL is the first matching entry.

Revision ID: 012
Revises: 011
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op


revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "idx_source_versions_url_seen_desc"


def upgrade() -> None:
    op.execute(
        f"CREATE INDEX {INDEX_NAME} "
        f"ON source_versions (source_url, last_seen_at DESC)"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
