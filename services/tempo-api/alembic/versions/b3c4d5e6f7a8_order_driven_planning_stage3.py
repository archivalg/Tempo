"""Order-driven-planning Stage 3: fill priorities, absenteeism rules, equipment pools, headcount
limits (tenant/site-scoped RLS).

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"
WIDE = "coalesce(current_setting('app.site_scope', true), '') IN ('', '*')"
IN_SCOPE = "site_id = ANY (string_to_array(current_setting('app.site_scope', true), ','))"
SITE_SCOPED_EXPR = f"{TENANT} AND ({WIDE} OR {IN_SCOPE})"


def _site_scoped_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{table}" FOR ALL TO tempo_app USING ({SITE_SCOPED_EXPR}) WITH CHECK ({SITE_SCOPED_EXPR})')


def _tenant_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{table}" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')


def upgrade() -> None:
    op.create_table("fill_priority",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("scope", sa.String(), nullable=False), sa.Column("value", sa.String(), nullable=False), sa.Column("priority", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "scope", "value", name="uq_fill_priority"))
    op.create_table("absenteeism_rule",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("activity", sa.String(), nullable=True),
        sa.Column("weekday", sa.String(), nullable=True), sa.Column("shift_code", sa.String(), nullable=True), sa.Column("absence_pct", sa.Float(), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "activity", "weekday", "shift_code", name="uq_absenteeism_rule"))
    op.create_table("equipment",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("equipment_id", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False), sa.Column("quantity_available", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "equipment_id", name="uq_equipment"))
    op.create_table("headcount_limit",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("activity", sa.String(), nullable=False),
        sa.Column("shift_code", sa.String(), nullable=True), sa.Column("min_headcount", sa.Integer(), nullable=False), sa.Column("max_headcount", sa.Integer(), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "activity", "shift_code", name="uq_headcount_limit"))
    for t in ("absenteeism_rule", "equipment", "headcount_limit"):
        _site_scoped_rls(t)
    _tenant_rls("fill_priority")


def downgrade() -> None:
    for t in ("fill_priority", "absenteeism_rule", "equipment", "headcount_limit"):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
        op.drop_table(t)
