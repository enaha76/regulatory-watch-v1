"""019 - Persist a short LLM-generated headline on change_events.

The inbox previously fell back to truncating the compliance summary
when no document title was available, producing rows like
"You must be aware that the Bureau of Alcohol, Tobacco, Firearms…".
The summary is *actionable* (correct for a summary) but not
*identifying* (wrong for a headline).

This column stores a 6–12 word headline produced alongside the
summary by the scoring LLM call. derive_title in alert_adapter.py
reads it before falling through to the older behaviour.

`headline`  varchar(160), nullable

Revision ID: 019
Revises: 018
Create Date: 2026-05-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "change_events",
        sa.Column("headline", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("change_events", "headline")
