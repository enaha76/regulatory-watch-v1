"""010 - Add origin / destination country arrays + trade-flow direction.

M5 prelude: enable filtering change_events by *who* the regulation applies
to (e.g. "show me every China-origin substantive event on HTS chapter 84
delivered into the US").

New columns on change_events
----------------------------
  origin_countries       TEXT[]     — ISO-3166 alpha-2 codes of goods /
                                      transactions the rule applies to.
                                      Populated by the significance LLM.
  destination_countries  TEXT[]     — jurisdictions the regulator governs.
                                      Auto-filled deterministically from
                                      the source URL (cbp.gov → ["US"],
                                      ec.europa.eu → ["EU"], …).
  trade_flow_direction   VARCHAR(12) — one of:
                                        'inbound'   — goods into dest
                                        'outbound'  — goods leaving dest
                                        'bilateral' — both
                                        'global'    — multilateral / N/A
                                        NULL        — unknown / irrelevant

All columns are nullable so existing rows stay valid.

Revision ID: 010
Revises: 009
Create Date: 2026-04-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TRADE_FLOW_VALUES = ("inbound", "outbound", "bilateral", "global")


def upgrade() -> None:
    op.add_column(
        "change_events",
        sa.Column(
            "origin_countries",
            sa.ARRAY(sa.String(length=8)),
            nullable=True,
        ),
    )
    op.add_column(
        "change_events",
        sa.Column(
            "destination_countries",
            sa.ARRAY(sa.String(length=8)),
            nullable=True,
        ),
    )
    op.add_column(
        "change_events",
        sa.Column(
            "trade_flow_direction",
            sa.String(length=12),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "ck_change_event_trade_flow_direction",
        "change_events",
        "trade_flow_direction IS NULL OR trade_flow_direction IN ("
        "'inbound','outbound','bilateral','global')",
    )
    # GIN indexes so filter queries like
    #   WHERE origin_countries @> ARRAY['CN']
    # are index-scans, not seq scans.
    op.create_index(
        "ix_change_events_origin_countries",
        "change_events",
        ["origin_countries"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_change_events_destination_countries",
        "change_events",
        ["destination_countries"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_change_events_trade_flow_direction",
        "change_events",
        ["trade_flow_direction"],
        postgresql_where=sa.text("trade_flow_direction IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_change_events_trade_flow_direction",
        table_name="change_events",
    )
    op.drop_index(
        "ix_change_events_destination_countries",
        table_name="change_events",
    )
    op.drop_index(
        "ix_change_events_origin_countries",
        table_name="change_events",
    )
    op.drop_constraint(
        "ck_change_event_trade_flow_direction",
        "change_events",
        type_="check",
    )
    op.drop_column("change_events", "trade_flow_direction")
    op.drop_column("change_events", "destination_countries")
    op.drop_column("change_events", "origin_countries")
