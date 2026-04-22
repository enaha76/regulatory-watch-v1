"""004 - Add source_versions + change_events tables

Adds the versioning layer that turns the raw ingestion pipeline into a
real change-detection system:

  - source_versions  : immutable history, one row per unique
                       (source_url, content_hash).
  - change_events    : one row per created/modified transition between
                       two source_versions (with unified diff + char
                       deltas, and a nullable LLM summary).

Revision ID: 004
Revises: 003
Create Date: 2026-04-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── source_versions ────────────────────────────────────────────────────
    op.create_table(
        "source_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column("source_type", sa.String(20), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_text", sa.Text, nullable=True),
        sa.Column("title", sa.Text, nullable=True),
        sa.Column("language", sa.String(10), nullable=True),
        sa.Column("page_count", sa.Integer, nullable=True),
        sa.Column("pages", sa.JSON, nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "source_url", "content_hash",
            name="uq_source_version_url_hash",
        ),
        sa.CheckConstraint(
            "source_type IN ('web','pdf','rss','xml','email')",
            name="ck_source_version_source_type",
        ),
    )
    op.create_index("ix_source_versions_source_url", "source_versions", ["source_url"])
    op.create_index("ix_source_versions_content_hash", "source_versions", ["content_hash"])
    op.create_index("ix_source_versions_last_seen_at", "source_versions", ["last_seen_at"])

    # ── change_events ──────────────────────────────────────────────────────
    op.create_table(
        "change_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("source_url", sa.Text, nullable=False),
        sa.Column(
            "new_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("source_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "prev_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("source_versions.id"),
            nullable=True,
        ),
        sa.Column("diff_kind", sa.String(20), nullable=False),
        sa.Column("added_chars", sa.Integer, nullable=False, server_default="0"),
        sa.Column("removed_chars", sa.Integer, nullable=False, server_default="0"),
        sa.Column("unified_diff", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "diff_kind IN ('created','modified')",
            name="ck_change_event_diff_kind",
        ),
    )
    op.create_index("ix_change_events_source_url", "change_events", ["source_url"])
    op.create_index("ix_change_events_detected_at", "change_events", ["detected_at"])
    op.create_index("ix_change_events_new_version_id", "change_events", ["new_version_id"])


def downgrade() -> None:
    op.drop_table("change_events")
    op.drop_table("source_versions")
