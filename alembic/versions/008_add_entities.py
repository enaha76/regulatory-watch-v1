"""008 - Promote affected_entities JSON to a queryable entity index

Today, `change_events.affected_entities` is a denormalized JSON array of
strings. That's fine for display, but it can't answer:

    "all critical events in the last 30 days mentioning FCA"
    "top 20 agencies cited across every change event"

This migration adds:

  - entities                  : canonical entity registry (one row per
                                distinct normalized entity). `canonical_key`
                                is what we dedupe on (lowercased + trimmed
                                + known acronym expansions — see
                                app.services.entity_index.normalize).
  - change_event_entities     : many-to-many join table. `mention_text`
                                preserves the original LLM surface form so
                                we never lose the exact wording.

The old `change_events.affected_entities` JSON column is KEPT for now —
it's still useful for single-event display and gives us a safety net
during the migration. A future cleanup migration can drop it once
every consumer reads from the join table.

Revision ID: 008
Revises: 007
Create Date: 2026-04-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Keep in sync with app.services.entity_index.ENTITY_TYPES
ENTITY_TYPES = (
    "agency",        # e.g. FCA, SEC, CBP, OFAC, FDA
    "regulation",    # e.g. 19 CFR 149, GDPR Art. 30, MiFID II
    "program",       # e.g. Importer Security Filing, Entity List
    "code",          # e.g. HS codes, CN codes, taxonomy identifiers
    "industry",      # e.g. "crypto exchanges", "pharmaceutical manufacturers"
    "other",
)


def upgrade() -> None:
    # ── entities ──────────────────────────────────────────────────────────
    op.create_table(
        "entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        # Normalized form used for dedup. MUST be unique and lowercase.
        sa.Column("canonical_key", sa.String(length=255), nullable=False),
        # Human-readable display form (first surface form we observe,
        # unless a known canonical replacement is applied).
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False, server_default="other"),
        sa.Column("mention_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("canonical_key", name="uq_entities_canonical_key"),
        sa.CheckConstraint(
            "entity_type IN ("
            "'agency','regulation','program','code','industry','other')",
            name="ck_entities_type",
        ),
    )
    op.create_index("ix_entities_entity_type", "entities", ["entity_type"])
    op.create_index(
        "ix_entities_last_seen_at", "entities", ["last_seen_at"],
    )

    # ── change_event_entities (m2m) ────────────────────────────────────────
    op.create_table(
        "change_event_entities",
        sa.Column(
            "change_event_id", UUID(as_uuid=True),
            sa.ForeignKey("change_events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "entity_id", UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Original LLM-produced surface form (before normalization), kept
        # so dashboards can show the exact wording the LLM extracted.
        sa.Column("mention_text", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_change_event_entities_entity",
        "change_event_entities", ["entity_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_change_event_entities_entity", table_name="change_event_entities")
    op.drop_table("change_event_entities")
    op.drop_index("ix_entities_last_seen_at", table_name="entities")
    op.drop_index("ix_entities_entity_type", table_name="entities")
    op.drop_table("entities")
