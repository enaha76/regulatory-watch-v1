"""013 - Add delivery channel + delivery-tracking fields for M5b.

M5 Part B turns "alerts sit in a database table" into "alerts arrive in
a channel the user actually watches." This migration adds:

  user_subscriptions.channel        — "email" | "slack" | "webhook" | "none"
  user_subscriptions.channel_target — optional override (override-email
                                      address, slack webhook, webhook URL)
  alerts.delivered_at               — set when a notifier reports success
  alerts.delivery_error             — last failure reason (truncated)
  alerts.delivery_attempts          — number of attempts so far

All new columns have safe defaults so existing rows remain valid.

Revision ID: 013
Revises: 012
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── user_subscriptions: channel routing ──────────────────────────
    op.add_column(
        "user_subscriptions",
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default="email",
        ),
    )
    op.add_column(
        "user_subscriptions",
        sa.Column("channel_target", sa.String(length=512), nullable=True),
    )
    op.create_check_constraint(
        "ck_user_subscriptions_channel",
        "user_subscriptions",
        "channel IN ('email','slack','webhook','none')",
    )

    # ── alerts: delivery tracking ────────────────────────────────────
    op.add_column(
        "alerts",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("delivery_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column(
            "delivery_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # Partial index speeds up the "find alerts that still need delivery"
    # query used by a future retry-sweeper (inbox-only subs excluded).
    op.execute(
        "CREATE INDEX idx_alerts_pending_delivery "
        "ON alerts (created_at) "
        "WHERE delivered_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alerts_pending_delivery")
    op.drop_column("alerts", "delivery_attempts")
    op.drop_column("alerts", "delivery_error")
    op.drop_column("alerts", "delivered_at")
    op.drop_constraint(
        "ck_user_subscriptions_channel",
        "user_subscriptions",
        type_="check",
    )
    op.drop_column("user_subscriptions", "channel_target")
    op.drop_column("user_subscriptions", "channel")
