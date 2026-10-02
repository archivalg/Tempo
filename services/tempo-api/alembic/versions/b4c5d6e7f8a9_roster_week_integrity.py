"""Roster integrity (roadmap M3): one live roster per site and week, unique version numbers.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE UNIQUE INDEX uq_roster_version_no ON roster_version (tenant_id, site_id, week_start, version_no)")
    op.execute("CREATE UNIQUE INDEX uq_roster_one_live ON roster_version (tenant_id, site_id, week_start) WHERE state IN ('published', 'reconciled')")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_roster_one_live")
    op.execute("DROP INDEX IF EXISTS uq_roster_version_no")
