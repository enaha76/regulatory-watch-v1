"""014 - Add `label` column to domains so the Add Source UI can persist a
user-supplied display name.

The `domains.domain` column is the unique technical key (e.g. "fca.org.uk")
and isn't user-friendly. The frontend's auto-derived names from the
authority lookup work for known regulators but fall back to ALL CAPS
hostname slugs for unknown ones. Allowing the user to type a clean name
("UK Financial Conduct Authority") makes the sources list readable.

NULL = no override; the source falls back to authority lookup → derived
name. Existing rows are not affected.

Revision ID: 014
Revises: 013
Create Date: 2026-05-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "domains",
        sa.Column("label", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("domains", "label")
