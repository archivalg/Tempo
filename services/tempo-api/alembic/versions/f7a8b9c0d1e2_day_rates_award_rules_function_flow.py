"""Arch completion pass: day rates (effective weekday activity rate), award rules (ordinary
hours/overtime multiplier, configurable), function/flow on work standards, worker award field.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"


def _tenant_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{table}" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')


def upgrade() -> None:
    op.add_column("work_standard", sa.Column("function", sa.String(), nullable=True))
    op.add_column("work_standard", sa.Column("flow", sa.String(), nullable=True))
    op.add_column("worker", sa.Column("award", sa.String(), nullable=True))

    op.create_table("day_rate",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("activity", sa.String(), nullable=False), sa.Column("weekday", sa.String(), nullable=False), sa.Column("rate_per_hour", sa.Float(), nullable=False),
        sa.UniqueConstraint("tenant_id", "activity", "weekday", name="uq_day_rate"))
    _tenant_rls("day_rate")

    op.create_table("award_rule",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("award_code", sa.String(), nullable=False), sa.Column("ordinary_hours_per_day", sa.Float(), nullable=False), sa.Column("overtime_multiplier", sa.Float(), nullable=False),
        sa.UniqueConstraint("tenant_id", "award_code", name="uq_award_rule"))
    _tenant_rls("award_rule")


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "award_rule"')
    op.drop_table("award_rule")
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "day_rate"')
    op.drop_table("day_rate")
    op.drop_column("worker", "award")
    op.drop_column("work_standard", "flow")
    op.drop_column("work_standard", "function")
