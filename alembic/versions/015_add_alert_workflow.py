"""015 - Alert workflow: assignment, status, comments, activity log.

Turns alerts from "items in an inbox" into "items a team actually
owns and resolves." Adds:

  alerts.workflow_status   — 'open' | 'in_progress' | 'done' | 'waived'
                              (the resolution state; orthogonal to the
                               existing notification status field)
  alerts.assigned_to       — email of the owner (NULL when unassigned)
  alerts.assigned_by       — email of whoever did the assigning
                              (reassignment audit)
  alerts.assigned_at       — when the current assignment was made
  alerts.due_date          — optional deadline for resolution
  alerts.resolution_note   — required when transitioning to
                              'done' or 'waived'; preserved as audit
  alerts.closed_at         — timestamp of terminal transition

  alert_comments           — threaded discussion per alert
  alert_activity           — audit trail (who changed what, when)

Notes on the two status fields
------------------------------
The existing `alerts.status` column (unread/read/dismissed) is kept
as-is for "inbox visibility" — did the user see this? Flag it?
`workflow_status` is independent: it tracks whether the TEAM has
worked the alert. A team lead can reassign an item the owner has
already marked read but not yet done.

Revision ID: 015
Revises: 014
Create Date: 2026-04-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── alerts: workflow columns ────────────────────────────────────
    op.add_column(
        "alerts",
        sa.Column(
            "workflow_status",
            sa.String(length=20),
            nullable=False,
            server_default="open",
        ),
    )
    op.add_column(
        "alerts",
        sa.Column("assigned_to", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("assigned_by", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("due_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("resolution_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "alerts",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_check_constraint(
        "ck_alerts_workflow_status",
        "alerts",
        "workflow_status IN ('open','in_progress','done','waived')",
    )
    # Terminal states must carry a resolution_note + closed_at;
    # non-terminal states must NOT have closed_at set. Keeps the
    # audit trail clean regardless of which endpoint wrote the row.
    op.create_check_constraint(
        "ck_alerts_closed_when_terminal",
        "alerts",
        "(workflow_status IN ('done','waived') AND closed_at IS NOT NULL "
        "AND resolution_note IS NOT NULL) "
        "OR (workflow_status IN ('open','in_progress') AND closed_at IS NULL)",
    )

    # Workflow dashboard queries need fast filtering by assignee and
    # status; also useful for "unassigned open alerts" triage views.
    op.create_index(
        "idx_alerts_workflow",
        "alerts",
        ["workflow_status", "assigned_to"],
    )
    op.create_index(
        "idx_alerts_due_date",
        "alerts",
        ["due_date"],
        postgresql_where=sa.text("due_date IS NOT NULL"),
    )

    # ── alert_comments ───────────────────────────────────────────────
    op.create_table(
        "alert_comments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "alert_id",
            sa.Uuid(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("author_email", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_alert_comments_alert_created",
        "alert_comments",
        ["alert_id", "created_at"],
    )

    # ── alert_activity (audit log) ───────────────────────────────────
    op.create_table(
        "alert_activity",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "alert_id",
            sa.Uuid(),
            sa.ForeignKey("alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("actor_email", sa.String(length=255), nullable=False),
        # 'assigned', 'unassigned', 'status_changed', 'commented',
        # 'due_date_changed' — extend as new actions appear.
        sa.Column("action", sa.String(length=30), nullable=False),
        # Free-form JSON payload: {"from": ..., "to": ..., "note": ...}.
        # Keeps the schema stable as new actions add new fields.
        sa.Column(
            "details",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_alert_activity_alert_created",
        "alert_activity",
        ["alert_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_alert_activity_alert_created", table_name="alert_activity")
    op.drop_table("alert_activity")
    op.drop_index("idx_alert_comments_alert_created", table_name="alert_comments")
    op.drop_table("alert_comments")

    op.drop_index("idx_alerts_due_date", table_name="alerts")
    op.drop_index("idx_alerts_workflow", table_name="alerts")
    op.drop_constraint("ck_alerts_closed_when_terminal", "alerts", type_="check")
    op.drop_constraint("ck_alerts_workflow_status", "alerts", type_="check")
    op.drop_column("alerts", "closed_at")
    op.drop_column("alerts", "resolution_note")
    op.drop_column("alerts", "due_date")
    op.drop_column("alerts", "assigned_at")
    op.drop_column("alerts", "assigned_by")
    op.drop_column("alerts", "assigned_to")
    op.drop_column("alerts", "workflow_status")
