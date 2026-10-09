"""Order-driven-planning Stage 2: process templates/steps, orders, order tasks, worker activity
rates, unit conversions (tenant/site-scoped RLS).

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
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
    op.create_table("process_template",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("process_code", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=True),
        sa.UniqueConstraint("tenant_id", "site_id", "process_code", "customer_id", name="uq_process_template"))
    op.create_table("process_step",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("process_template_id", sa.String(), sa.ForeignKey("process_template.id"), nullable=False, index=True),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("activity", sa.String(), nullable=False),
        sa.Column("lag_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("process_template_id", "sequence", name="uq_process_step_sequence"))
    op.create_table("order_",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("order_ref", sa.String(), nullable=False),
        sa.Column("customer_id", sa.String(), nullable=True),
        sa.Column("order_received", sa.DateTime(timezone=True), nullable=False), sa.Column("despatch_due", sa.DateTime(timezone=True), nullable=False),
        sa.Column("units", sa.Float(), nullable=True), sa.Column("lines", sa.Float(), nullable=True), sa.Column("unit", sa.String(), nullable=False, server_default="units"),
        sa.Column("process_template_id", sa.String(), sa.ForeignKey("process_template.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.UniqueConstraint("tenant_id", "site_id", "order_ref", name="uq_order_ref"))
    op.create_table("order_task",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("order_id", sa.String(), sa.ForeignKey("order_.id"), nullable=False, index=True),
        sa.Column("sequence", sa.Integer(), nullable=False), sa.Column("activity", sa.String(), nullable=False),
        sa.Column("lag_minutes", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("worker_activity_rate",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("worker_id", sa.String(), sa.ForeignKey("worker.worker_id"), nullable=False, index=True),
        sa.Column("activity", sa.String(), nullable=False), sa.Column("unit", sa.String(), nullable=False, server_default="units"),
        sa.Column("rate_per_hour", sa.Float(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False), sa.Column("effective_to", sa.Date(), nullable=True))
    op.create_table("unit_conversion",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("activity", sa.String(), nullable=True), sa.Column("from_unit", sa.String(), nullable=False),
        sa.Column("to_unit", sa.String(), nullable=False), sa.Column("factor", sa.Float(), nullable=False))
    for t in ("process_template", "order_"):
        _site_scoped_rls(t)
    for t in ("process_step", "order_task", "worker_activity_rate", "unit_conversion"):
        _tenant_rls(t)


def downgrade() -> None:
    for t in ("process_template", "order_", "process_step", "order_task", "worker_activity_rate", "unit_conversion"):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
    op.drop_table("order_task")
    op.drop_table("order_")
    op.drop_table("worker_activity_rate")
    op.drop_table("unit_conversion")
    op.drop_table("process_step")
    op.drop_table("process_template")
