"""Order-driven-planning Stage 4: grade/provider/effective-dated cost rules, productivity loss
(congestion/off-task), staging capacity and movements (tenant/site-scoped RLS).

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"
WIDE = "coalesce(current_setting('app.site_scope', true), '') IN ('', '*')"
IN_SCOPE = "site_id = ANY (string_to_array(current_setting('app.site_scope', true), ','))"
SITE_SCOPED_EXPR = f"{TENANT} AND ({WIDE} OR {IN_SCOPE})"


def _site_scoped_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{table}" FOR ALL TO tempo_app USING ({SITE_SCOPED_EXPR}) WITH CHECK ({SITE_SCOPED_EXPR})')


def upgrade() -> None:
    op.add_column("labour_cost_rule", sa.Column("position_grade", sa.String(), nullable=True))
    op.add_column("labour_cost_rule", sa.Column("provider_id", sa.String(), sa.ForeignKey("labour_provider.provider_id"), nullable=True))
    op.add_column("labour_cost_rule", sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("labour_cost_rule", sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True))

    op.create_table("productivity_loss",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("loss_type", sa.String(), nullable=False),
        sa.Column("activity", sa.String(), nullable=True), sa.Column("weekday", sa.String(), nullable=True), sa.Column("shift_code", sa.String(), nullable=True),
        sa.Column("percent_loss", sa.Float(), nullable=True), sa.Column("off_task_hours", sa.Float(), nullable=True))
    op.create_table("staging_capacity",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("zone_id", sa.String(), nullable=False),
        sa.Column("capacity", sa.Float(), nullable=False), sa.Column("unit", sa.String(), nullable=False),
        sa.UniqueConstraint("tenant_id", "site_id", "zone_id", name="uq_staging_capacity"))
    op.create_table("staging_movement",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("zone_id", sa.String(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False), sa.Column("movement_type", sa.String(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False), sa.Column("unit", sa.String(), nullable=False))
    for t in ("productivity_loss", "staging_capacity", "staging_movement"):
        _site_scoped_rls(t)


def downgrade() -> None:
    for t in ("productivity_loss", "staging_capacity", "staging_movement"):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
        op.drop_table(t)
    op.drop_column("labour_cost_rule", "effective_to")
    op.drop_column("labour_cost_rule", "effective_from")
    op.drop_column("labour_cost_rule", "provider_id")
    op.drop_column("labour_cost_rule", "position_grade")
