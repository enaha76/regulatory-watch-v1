"""007 - Add regulatory topic classification to change_events

Adds a `topic` column populated by the same L3 LLM call that produces
significance_score, change_type, etc. The topic is a fixed-vocabulary
label from a curated regulatory taxonomy — it powers M5 personalization
("subscribe me to financial_services and sanctions_export_control")
without needing a second LLM round-trip.

New columns
-----------
  topic VARCHAR(40) — one of TOPICS (see CHECK constraint) or NULL
                      (NULL until the event has been scored).

Indices
-------
  ix_change_events_topic   — covering index for topic filters
                             (used by alert matcher + dashboards).

Revision ID: 007
Revises: 006
Create Date: 2026-04-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Keep in sync with app.services.significance.TOPICS
# Taxonomy chosen to map 1:1 to real compliance-officer domains.
# "other" is the catch-all — keep the vocabulary small so
# personalization + filtering stay tractable.
TOPICS = (
    "customs_trade",
    "financial_services",
    "data_privacy",
    "environmental",
    "healthcare_pharma",
    "sanctions_export_control",
    "labor_employment",
    "tax_accounting",
    "consumer_protection",
    "corporate_governance",
    "other",
)


def upgrade() -> None:
    op.add_column(
        "change_events",
        sa.Column("topic", sa.String(length=40), nullable=True),
    )

    topics_csv = ", ".join(f"'{t}'" for t in TOPICS)
    op.create_check_constraint(
        "ck_change_event_topic",
        "change_events",
        f"topic IS NULL OR topic IN ({topics_csv})",
    )

    op.create_index(
        "ix_change_events_topic",
        "change_events",
        ["topic", "detected_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_change_events_topic", table_name="change_events")
    op.drop_constraint("ck_change_event_topic", "change_events")
    op.drop_column("change_events", "topic")
