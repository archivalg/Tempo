"""Order-driven-planning integration increment, priority 2: recurring weekly availability pattern
and personal start/finish windows (tenant-scoped RLS).

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    op.create_table("weekly_availability_pattern",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("worker_id", sa.String(), sa.ForeignKey("worker.worker_id"), nullable=False, index=True),
        sa.Column("weekday", sa.String(), nullable=False), sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("earliest_start", sa.String(), nullable=True), sa.Column("latest_finish", sa.String(), nullable=True),
        sa.UniqueConstraint("tenant_id", "worker_id", "weekday", name="uq_weekly_availability_pattern"))
    op.execute('ALTER TABLE "weekly_availability_pattern" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "weekly_availability_pattern" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "weekly_availability_pattern"')
    op.drop_table("weekly_availability_pattern")
