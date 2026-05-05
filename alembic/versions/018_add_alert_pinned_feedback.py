"""018 - Persist alert pinned + user_feedback.

The frontend has been showing a pin button and thumbs up/down/partial
buttons for a while, but the PATCH /api/v2/alerts/{id} handler swallowed
those fields because the columns didn't exist. This adds them so user
feedback survives a refresh.

`pinned`        bool, default False, NOT NULL
`user_feedback` varchar, nullable, CHECK constraint on the 3 allowed
                values

Revision ID: 018
Revises: 017
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "alerts",
        sa.Column(
            "pinned",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "alerts",
        sa.Column("user_feedback", sa.String(length=24), nullable=True),
    )
    op.create_check_constraint(
        "ck_alerts_user_feedback",
        "alerts",
        "user_feedback IS NULL OR user_feedback IN "
        "('relevant','not_relevant','partially_relevant')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_alerts_user_feedback", "alerts", type_="check")
    op.drop_column("alerts", "user_feedback")
    op.drop_column("alerts", "pinned")
