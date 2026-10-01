"""Demand override approval (second person for large changes): decision columns.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("demand_override", sa.Column("decided_by", sa.String(), nullable=True))
    op.add_column("demand_override", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("demand_override", sa.Column("decision_note", sa.String(), nullable=True))


def downgrade() -> None:
    for c in ("decision_note", "decided_at", "decided_by"):
        op.drop_column("demand_override", c)
