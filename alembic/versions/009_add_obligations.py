"""009 - Add structured obligations extracted from high-significance changes

M4 phase 3: for events scored substantive or critical (significance_score
>= 0.6), a second (cheaper) LLM call extracts the specific ACTIONABLE
obligations a compliance team must take. Unlike the compliance_summary
field on change_events (which is a free-text paragraph), this is
machine-readable — (actor, action, condition, deadline, penalty) — so
that M5 alerts and M6 dashboards can surface and filter them.

Gating on score >= 0.6 keeps the marginal LLM cost bounded (typo /
cosmetic events get zero obligation calls).

Columns
-------
  actor           VARCHAR(255) NOT NULL  — who must do it ("importers",
                                           "financial institutions", …)
  action          TEXT         NOT NULL  — what they must do / not do
  condition       TEXT                   — when/if (triggering scenario)
  deadline_text   VARCHAR(255)           — human-readable deadline
                                           ("30 June 2026", "within 30 days of …")
  deadline_date   DATE                   — parsed deadline when possible
  penalty         TEXT                   — consequences of non-compliance
  obligation_type VARCHAR(30)            — reporting|prohibition|threshold|
                                           disclosure|registration|penalty|other
  llm_model       VARCHAR(50)
  extracted_at    TIMESTAMP tz NOT NULL

Revision ID: 009
Revises: 008
Create Date: 2026-04-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Keep in sync with app.services.obligations.OBLIGATION_TYPES
OBLIGATION_TYPES = (
    "reporting",       # file / submit / report
    "prohibition",     # must not / may not
    "threshold",       # quantitative limits (capital ratios, HS quotas…)
    "disclosure",      # publish / inform / disclose
    "registration",    # register / license / notify an authority
    "penalty",         # payment of fine / fee / sanction
    "other",
)


def upgrade() -> None:
    op.create_table(
        "obligations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "change_event_id", UUID(as_uuid=True),
            sa.ForeignKey("change_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("condition", sa.Text, nullable=True),
        sa.Column("deadline_text", sa.String(length=255), nullable=True),
        sa.Column("deadline_date", sa.Date, nullable=True),
        sa.Column("penalty", sa.Text, nullable=True),
        sa.Column(
            "obligation_type", sa.String(length=30),
            nullable=False, server_default="other",
        ),
        sa.Column("llm_model", sa.String(length=50), nullable=True),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "obligation_type IN ("
            "'reporting','prohibition','threshold','disclosure',"
            "'registration','penalty','other')",
            name="ck_obligations_type",
        ),
    )
    op.create_index(
        "ix_obligations_change_event_id",
        "obligations", ["change_event_id"],
    )
    op.create_index(
        "ix_obligations_deadline_date",
        "obligations", ["deadline_date"],
        postgresql_where=sa.text("deadline_date IS NOT NULL"),
    )

    # Mark which events have been through obligation extraction so we
    # can batch-gate (and re-extract on demand). A NULL timestamp means
    # "never attempted"; a non-NULL with zero obligations means "tried,
    # nothing found — don't retry on every alert run".
    op.add_column(
        "change_events",
        sa.Column("obligations_extracted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("change_events", "obligations_extracted_at")
    op.drop_index("ix_obligations_deadline_date", table_name="obligations")
    op.drop_index("ix_obligations_change_event_id", table_name="obligations")
    op.drop_table("obligations")
