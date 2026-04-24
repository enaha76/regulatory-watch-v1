"""014 - Add trigger/source quote columns for explainability (M5c).

An alert without a citation is a score without evidence. This
migration adds quote + character-offset fields so the UI and email
templates can show users *exactly which sentence* triggered a score
or established an obligation.

  change_events.trigger_quote        — LLM-emitted verbatim quote
                                       that best demonstrates the change
  change_events.trigger_span_start   — char offset of quote in
                                       source_versions.raw_text
                                       (NULL when quote couldn't be located)
  change_events.trigger_span_end     — exclusive end offset

  obligations.source_quote           — LLM-emitted quote that
                                       establishes THIS obligation
  obligations.source_span_start      — char offset in the
                                       source_versions.raw_text at
                                       time of extraction
  obligations.source_span_end        — exclusive end offset

Both (start, end) pairs must be set together or both NULL, enforced
by a CHECK constraint so consumers never see a half-populated span.

Revision ID: 014
Revises: 013
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── change_events: trigger quote + span ──────────────────────────
    op.add_column(
        "change_events",
        sa.Column("trigger_quote", sa.Text(), nullable=True),
    )
    op.add_column(
        "change_events",
        sa.Column("trigger_span_start", sa.Integer(), nullable=True),
    )
    op.add_column(
        "change_events",
        sa.Column("trigger_span_end", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_change_events_trigger_span_paired",
        "change_events",
        "(trigger_span_start IS NULL) = (trigger_span_end IS NULL)",
    )
    op.create_check_constraint(
        "ck_change_events_trigger_span_ordered",
        "change_events",
        "trigger_span_start IS NULL OR trigger_span_start <= trigger_span_end",
    )

    # ── obligations: source quote + span ─────────────────────────────
    op.add_column(
        "obligations",
        sa.Column("source_quote", sa.Text(), nullable=True),
    )
    op.add_column(
        "obligations",
        sa.Column("source_span_start", sa.Integer(), nullable=True),
    )
    op.add_column(
        "obligations",
        sa.Column("source_span_end", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_obligations_source_span_paired",
        "obligations",
        "(source_span_start IS NULL) = (source_span_end IS NULL)",
    )
    op.create_check_constraint(
        "ck_obligations_source_span_ordered",
        "obligations",
        "source_span_start IS NULL OR source_span_start <= source_span_end",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_obligations_source_span_ordered", "obligations", type_="check",
    )
    op.drop_constraint(
        "ck_obligations_source_span_paired", "obligations", type_="check",
    )
    op.drop_column("obligations", "source_span_end")
    op.drop_column("obligations", "source_span_start")
    op.drop_column("obligations", "source_quote")

    op.drop_constraint(
        "ck_change_events_trigger_span_ordered", "change_events", type_="check",
    )
    op.drop_constraint(
        "ck_change_events_trigger_span_paired", "change_events", type_="check",
    )
    op.drop_column("change_events", "trigger_span_end")
    op.drop_column("change_events", "trigger_span_start")
    op.drop_column("change_events", "trigger_quote")
