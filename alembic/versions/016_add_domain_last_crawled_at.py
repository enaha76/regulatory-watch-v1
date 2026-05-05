"""016 - Add `last_crawled_at` to domains so the per-source scheduler
(`crawl_due_domains`) can tell which domains are actually due.

Before this column existed, the beat task tried to derive "last crawled"
from `fetch_runs.MAX(started_at)` — but `fetch_runs` is never populated
by anything in the codebase, so the answer was always NULL and every
domain looked overdue at every tick. The scheduler enqueued the same
crawls every 5 minutes regardless of frequency.

`last_crawled_at` is set at the START of each web_crawl_task run so:
  - the scheduler stops re-enqueueing the same domain during a long crawl
  - failed crawls don't cause endless retries within the same window
  - the column reflects "we tried to crawl recently" semantics

Revision ID: 016
Revises: 015
Create Date: 2026-05-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column(
            "last_crawled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_domains_last_crawled_at",
        "domains",
        ["last_crawled_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_domains_last_crawled_at", table_name="domains")
    op.drop_column("domains", "last_crawled_at")
