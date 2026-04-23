"""011 - Add user_subscriptions and alerts tables for M5 Alerting Engine.

M5 enables user-specific alerting by matching newly scored ChangeEvents
against user-defined subscription profiles.  Two tables:

  user_subscriptions  — one row per subscription "rule" a user configures.
                         Combines structured metadata pre-filters (topics,
                         countries, min_significance) with PostgreSQL
                         full-text keyword matching via TSQuery.

  alerts              — one row per (subscription, change_event) match.
                         Unique constraint prevents duplicates on retry.

Revision ID: 011
Revises: 010
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── user_subscriptions ───────────────────────────────────────────
    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_email", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False,
                  server_default="Default Subscription"),
        # Stage 1: structured metadata pre-filters
        sa.Column("topics", sa.ARRAY(sa.String(length=40)), nullable=True),
        sa.Column("origin_countries",
                  sa.ARRAY(sa.String(length=8)), nullable=True),
        sa.Column("destination_countries",
                  sa.ARRAY(sa.String(length=8)), nullable=True),
        sa.Column("min_significance", sa.Float(), nullable=False,
                  server_default="0.6"),
        # Stage 2: full-text keyword percolation
        sa.Column("keyword_query", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False,
                  server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "min_significance >= 0.0 AND min_significance <= 1.0",
            name="ck_user_subscriptions_min_significance",
        ),
    )
    op.create_index("ix_user_subscriptions_user_email",
                    "user_subscriptions", ["user_email"])
    op.create_index("ix_user_subscriptions_is_active",
                    "user_subscriptions", ["is_active"])
    # GIN indexes for fast array-overlap queries in the matching engine.
    op.create_index("ix_user_subscriptions_topics",
                    "user_subscriptions", ["topics"],
                    postgresql_using="gin")
    op.create_index("ix_user_subscriptions_origin_countries",
                    "user_subscriptions", ["origin_countries"],
                    postgresql_using="gin")
    op.create_index("ix_user_subscriptions_destination_countries",
                    "user_subscriptions", ["destination_countries"],
                    postgresql_using="gin")

    # ── alerts ───────────────────────────────────────────────────────
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("subscription_id", sa.Uuid(),
                  sa.ForeignKey("user_subscriptions.id"), nullable=False),
        sa.Column("change_event_id", sa.Uuid(),
                  sa.ForeignKey("change_events.id"), nullable=False),
        sa.Column("matched_keywords", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False,
                  server_default="unread"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("subscription_id", "change_event_id",
                            name="uq_alerts_subscription_event"),
        sa.CheckConstraint(
            "status IN ('unread','read','dismissed')",
            name="ck_alerts_status",
        ),
    )
    op.create_index("ix_alerts_subscription_id",
                    "alerts", ["subscription_id"])
    op.create_index("ix_alerts_change_event_id",
                    "alerts", ["change_event_id"])


def downgrade() -> None:
    op.drop_table("alerts")
    op.drop_table("user_subscriptions")
