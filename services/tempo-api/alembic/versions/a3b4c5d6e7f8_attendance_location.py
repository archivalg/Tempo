"""Location at the moment of a punch (roadmap M2): per-site location mode, and the position/distance/status stored on each punch.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attendance_policy", sa.Column("location_mode", sa.String(), nullable=False, server_default="off"))
    for c in (sa.Column("latitude", sa.Float(), nullable=True), sa.Column("longitude", sa.Float(), nullable=True), sa.Column("accuracy_m", sa.Float(), nullable=True),
              sa.Column("distance_m", sa.Float(), nullable=True), sa.Column("location_status", sa.String(), nullable=False, server_default="not_requested")):
        op.add_column("attendance_punch", c)


def downgrade() -> None:
    for c in ("location_status", "distance_m", "accuracy_m", "longitude", "latitude"):
        op.drop_column("attendance_punch", c)
    op.drop_column("attendance_policy", "location_mode")
