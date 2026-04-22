"""006 - Add LLM significance scoring to change_events

Adds the fields produced by the Layer-3 significance scorer. All
columns are nullable — a ChangeEvent exists *before* it is scored (it
is enqueued for scoring after emission), and some events may never be
scored (e.g. when OPENAI_API_KEY is absent or the LLM keeps erroring).

New columns
-----------
  significance_score FLOAT (0.0–1.0)   — how important is the change
  change_type        VARCHAR(30)       — categorical label (see CHECK)
  affected_entities  JSON              — list of strings
  deadline_changes   JSON              — list of {old, new, deadline_text}
  llm_model          VARCHAR(50)       — model that produced the score
  llm_error          TEXT              — last error if scoring failed
  scored_at          TIMESTAMP tz      — when scoring completed

The existing `summary` column on change_events is repurposed as the
LLM-produced compliance_summary (plain-English explanation).

Revision ID: 006
Revises: 005
Create Date: 2026-04-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Keep in sync with app.services.significance.CHANGE_TYPES
CHANGE_TYPES = (
    "typo_or_cosmetic",
    "minor_wording",
    "clarification",
    "substantive",
    "critical",
)


def upgrade() -> None:
    op.add_column("change_events", sa.Column("significance_score", sa.Float(), nullable=True))
    op.add_column("change_events", sa.Column("change_type", sa.String(length=30), nullable=True))
    op.add_column("change_events", sa.Column("affected_entities", sa.JSON(), nullable=True))
    op.add_column("change_events", sa.Column("deadline_changes", sa.JSON(), nullable=True))
    op.add_column("change_events", sa.Column("llm_model", sa.String(length=50), nullable=True))
    op.add_column("change_events", sa.Column("llm_error", sa.Text(), nullable=True))
    op.add_column(
        "change_events",
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Bound the score to [0, 1]
    op.create_check_constraint(
        "ck_change_event_significance_score_range",
        "change_events",
        "significance_score IS NULL OR (significance_score >= 0.0 AND significance_score <= 1.0)",
    )

    # Constrain the change_type vocabulary
    types_csv = ", ".join(f"'{t}'" for t in CHANGE_TYPES)
    op.create_check_constraint(
        "ck_change_event_change_type",
        "change_events",
        f"change_type IS NULL OR change_type IN ({types_csv})",
    )

    # Partial index to quickly find unscored events for the backlog worker.
    op.create_index(
        "ix_change_events_unscored",
        "change_events",
        ["detected_at"],
        unique=False,
        postgresql_where=sa.text("significance_score IS NULL AND llm_error IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_change_events_unscored", table_name="change_events")
    op.drop_constraint("ck_change_event_change_type", "change_events")
    op.drop_constraint("ck_change_event_significance_score_range", "change_events")
    op.drop_column("change_events", "scored_at")
    op.drop_column("change_events", "llm_error")
    op.drop_column("change_events", "llm_model")
    op.drop_column("change_events", "deadline_changes")
    op.drop_column("change_events", "affected_entities")
    op.drop_column("change_events", "change_type")
    op.drop_column("change_events", "significance_score")
