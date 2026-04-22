"""001 - Initial schema: domains, urls, fetch_runs, fetch_attempts

Revision ID: 001
Revises: None
Create Date: 2026-03-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects.postgresql import UUID, JSON

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Domains ──────────────────────────────────────────
    op.create_table(
        "domains",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("domain", sa.String(255), nullable=False, unique=True, index=True),
        sa.Column("seed_urls", JSON, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("rate_limit_rps", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','paused','archived')", name="ck_domain_status"),
    )

    # ── URLs ─────────────────────────────────────────────
    op.create_table(
        "urls",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id"), nullable=False, index=True),
        sa.Column("url", sa.Text, nullable=False, unique=True),
        sa.Column("state", sa.String(20), nullable=False, server_default="discovered", index=True),
        sa.Column("priority", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("relevance_score", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("hub_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("trap_score", sa.Float, nullable=False, server_default="0.0"),
        sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer, nullable=True),
        sa.Column("last_content_hash", sa.String(128), nullable=True),
        sa.Column("last_etag", sa.String(256), nullable=True),
        sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("fetch_interval_hours", sa.Integer, nullable=False, server_default="168"),
        sa.Column("error_streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_from_url_id", UUID(as_uuid=True), sa.ForeignKey("urls.id"), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('discovered','queued','fetched','failed','ignored','blocked')",
            name="ck_url_state",
        ),
    )

    # ── Fetch Runs ───────────────────────────────────────
    op.create_table(
        "fetch_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("domain_id", UUID(as_uuid=True), sa.ForeignKey("domains.id"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("planned_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fetched_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("changed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("alert_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','cancelled')",
            name="ck_fetchrun_status",
        ),
    )

    # ── Fetch Attempts ───────────────────────────────────
    op.create_table(
        "fetch_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("url_id", UUID(as_uuid=True), sa.ForeignKey("urls.id"), nullable=False, index=True),
        sa.Column("run_id", UUID(as_uuid=True), sa.ForeignKey("fetch_runs.id"), nullable=False, index=True),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("content_hash", sa.String(128), nullable=True),
        sa.Column("diff_status", sa.String(20), nullable=True),
        sa.Column("raw_html_uri", sa.String(512), nullable=True),
        sa.Column("extracted_text_uri", sa.String(512), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fetch_attempts")
    op.drop_table("fetch_runs")
    op.drop_table("urls")
    op.drop_table("domains")
