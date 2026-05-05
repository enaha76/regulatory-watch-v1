"""017 - Add per-source max_pages cap to domains.

The Add Source / Edit Source UI lets users pick how deep each crawl
should go. NULL = use platform default (CRAWL_DEFAULT_MAX_PAGES, 50).
Range capped at 10,000 to protect against typos that could trigger
runaway crawls + LLM costs.

Revision ID: 017
Revises: 016
Create Date: 2026-05-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column("max_pages", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_domain_max_pages_range",
        "domains",
        "max_pages IS NULL OR (max_pages >= 1 AND max_pages <= 10000)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_domain_max_pages_range", "domains", type_="check")
    op.drop_column("domains", "max_pages")
