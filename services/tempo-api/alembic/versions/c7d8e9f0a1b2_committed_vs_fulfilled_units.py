"""Separate a committed run's PLANNED allocation (order_.committed_units, new) from CONFIRMED actual
completion (order_.fulfilled_units, existing) — committing a roster is not the same as the work
physically happening (see docs/order-driven-planning.md: "committed does not mean physically
fulfilled").

Revision ID: c7d8e9f0a1b2
Revises: ab12cd34ef56
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, Sequence[str], None] = "ab12cd34ef56"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("order_", sa.Column("committed_units", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("order_", "committed_units")
