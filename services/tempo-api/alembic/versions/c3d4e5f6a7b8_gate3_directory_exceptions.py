"""Directory (site/customer/zone), worker PII, source freshness, exception cases — each with tenant RLS.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None

TABLES = ["site", "customer", "zone", "worker_person", "data_source_status", "exception_case"]
EXPR = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    # A forecast series must be single-granularity: daily totals (1440) drive the Holt forecast,
    # hourly rows (60) carry the intraday shape and actuals.
    op.add_column("demand_bucket", sa.Column("bucket_minutes", sa.Integer(), nullable=False, server_default="60"))
    op.create_table("site",
        sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("site_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False), sa.Column("timezone", sa.String(), nullable=False),
        sa.Column("operating_mode", sa.String(), nullable=False, server_default="standalone"),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.create_table("customer",
        sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("customer_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False, server_default="active"))
    op.create_table("zone",
        sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("site_id", sa.String(), primary_key=True),
        sa.Column("zone_id", sa.String(), primary_key=True), sa.Column("name", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("worker_person",
        sa.Column("worker_id", sa.String(), sa.ForeignKey("worker.worker_id"), primary_key=True),
        sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("display_name", sa.String(), nullable=False), sa.Column("employee_no", sa.String(), nullable=True),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("data_source_status",
        sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("site_id", sa.String(), primary_key=True),
        sa.Column("source_key", sa.String(), primary_key=True), sa.Column("label", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False), sa.Column("mode", sa.String(), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stale_after_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("note", sa.String(), nullable=True))
    op.create_table("exception_case",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("kind", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False), sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("worker_id", sa.String(), nullable=True), sa.Column("shift_id", sa.String(), nullable=True),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("state", sa.String(), nullable=False, server_default="detected"),
        sa.Column("owner_user_id", sa.String(), nullable=True), sa.Column("resolution", sa.String(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"),
        sa.UniqueConstraint("tenant_id", "dedup_key", name="uq_exception_dedup"))
    for t in TABLES:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{t}" FOR ALL TO tempo_app USING ({EXPR}) WITH CHECK ({EXPR})')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{t}" TO tempo_app')


def downgrade() -> None:
    op.drop_column("demand_bucket", "bucket_minutes")
    for t in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
        op.drop_table(t)
