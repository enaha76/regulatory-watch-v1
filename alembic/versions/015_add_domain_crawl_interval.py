"""015 - Add `crawl_interval_seconds` to domains for per-source schedules.

The Add Source UI lets users pick how often each source is crawled. We
store the interval in seconds (NULL = use the platform default — currently
24h). A new beat task `crawl_due_domains` reads this column to decide
which sources are due for a fresh crawl on each tick.

Revision ID: 015
Revises: 014
Create Date: 2026-05-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column("crawl_interval_seconds", sa.Integer(), nullable=True),
    )
    # Allow only positive intervals (or NULL for "default").
    op.create_check_constraint(
        "ck_domain_crawl_interval_positive",
        "domains",
        "crawl_interval_seconds IS NULL OR crawl_interval_seconds > 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_domain_crawl_interval_positive",
        "domains",
        type_="check",
    )
    op.drop_column("domains", "crawl_interval_seconds")
