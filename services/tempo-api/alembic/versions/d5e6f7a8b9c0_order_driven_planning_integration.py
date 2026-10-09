"""Order-driven-planning integration increment: indirect headcount requirements, equipment/zone on
process steps, worker position grade (tenant/site-scoped RLS; additive nullable columns elsewhere).

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"
WIDE = "coalesce(current_setting('app.site_scope', true), '') IN ('', '*')"
IN_SCOPE = "site_id = ANY (string_to_array(current_setting('app.site_scope', true), ','))"
SITE_SCOPED_EXPR = f"{TENANT} AND ({WIDE} OR {IN_SCOPE})"


def upgrade() -> None:
    op.add_column("process_step", sa.Column("equipment_id", sa.String(), nullable=True))
    op.add_column("process_step", sa.Column("zone_id", sa.String(), nullable=True))
    op.add_column("worker", sa.Column("position_grade", sa.String(), nullable=True))

    op.create_table("indirect_headcount_requirement",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("role", sa.String(), nullable=False),
        sa.Column("weekday", sa.String(), nullable=False), sa.Column("start_time", sa.String(), nullable=False),
        sa.Column("end_time", sa.String(), nullable=False), sa.Column("headcount", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "role", "weekday", "start_time", "end_time", name="uq_indirect_headcount"))
    op.execute('ALTER TABLE "indirect_headcount_requirement" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "indirect_headcount_requirement" FOR ALL TO tempo_app USING ({SITE_SCOPED_EXPR}) WITH CHECK ({SITE_SCOPED_EXPR})')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "indirect_headcount_requirement"')
    op.drop_table("indirect_headcount_requirement")
    op.drop_column("worker", "position_grade")
    op.drop_column("process_step", "zone_id")
    op.drop_column("process_step", "equipment_id")
