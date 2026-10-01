"""Customer data ingestion (roadmap M1): import batches/rows/mappings, supplied forecasts, workload events, actuals policy.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None
TENANT = "tenant_id = current_setting('app.tenant_id', true)"
WIDE = "coalesce(current_setting('app.site_scope', true), '') IN ('', '*')"
IN_SCOPE = "site_id = ANY (string_to_array(current_setting('app.site_scope', true), ','))"
SITE_KEYED = ["supplied_forecast", "workload_event", "actuals_policy", "site_forecast_preference"]
TENANT_ONLY = ["import_batch", "import_row", "import_mapping"]
NO_DELETE = ["import_batch", "import_row", "workload_event", "supplied_forecast"]
TS = sa.DateTime(timezone=True)


def _t(name, *cols, **kw):
    op.create_table(name, *cols, **kw)


def upgrade() -> None:
    _t("import_batch",
       sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
       sa.Column("data_class", sa.String(), nullable=False), sa.Column("entity", sa.String(), nullable=True), sa.Column("channel", sa.String(), nullable=False),
       sa.Column("source_label", sa.String(), nullable=False, server_default=""), sa.Column("content_sha256", sa.String(), nullable=False, index=True),
       sa.Column("contract_version", sa.String(), nullable=False, server_default="1.0"), sa.Column("state", sa.String(), nullable=False, server_default="validated"),
       sa.Column("mode", sa.String(), nullable=False, server_default="upsert"), sa.Column("idempotency_key", sa.String(), nullable=True, index=True),
       sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"), sa.Column("ok_rows", sa.Integer(), nullable=False, server_default="0"),
       sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"), sa.Column("warning_rows", sa.Integer(), nullable=False, server_default="0"),
       sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"), sa.Column("created_by", sa.String(), nullable=False),
       sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()), sa.Column("applied_by", sa.String(), nullable=True), sa.Column("applied_at", TS, nullable=True),
       sa.Column("undone_by", sa.String(), nullable=True), sa.Column("undone_at", TS, nullable=True))
    _t("import_row",
       sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True), sa.Column("batch_id", sa.String(), nullable=False, index=True),
       sa.Column("row_no", sa.Integer(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("messages", sa.JSON(), nullable=False, server_default="[]"),
       sa.Column("raw", sa.JSON(), nullable=False, server_default="{}"), sa.Column("normalised", sa.JSON(), nullable=True), sa.Column("before", sa.JSON(), nullable=True),
       sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()))
    _t("import_mapping",
       sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True), sa.Column("data_class", sa.String(), nullable=False),
       sa.Column("entity", sa.String(), nullable=False, server_default=""), sa.Column("name", sa.String(), nullable=False, server_default="default"),
       sa.Column("mapping", sa.JSON(), nullable=False, server_default="{}"), sa.Column("updated_by", sa.String(), nullable=False),
       sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
       sa.UniqueConstraint("tenant_id", "data_class", "entity", "name", name="uq_import_mapping"))
    _t("supplied_forecast",
       sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True), sa.Column("site_id", sa.String(), nullable=False, index=True),
       sa.Column("activity", sa.String(), nullable=False), sa.Column("bucket_start", TS, nullable=False), sa.Column("bucket_minutes", sa.Integer(), nullable=False),
       sa.Column("units", sa.Float(), nullable=False), sa.Column("lower", sa.Float(), nullable=True), sa.Column("upper", sa.Float(), nullable=True),
       sa.Column("version", sa.String(), nullable=False), sa.Column("batch_id", sa.String(), nullable=False, index=True), sa.Column("generated_at", TS, nullable=True),
       sa.Column("state", sa.String(), nullable=False, server_default="active"), sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()))
    _t("workload_event",
       sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True), sa.Column("source", sa.String(), nullable=False),
       sa.Column("event_id", sa.String(), nullable=False), sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("activity", sa.String(), nullable=False),
       sa.Column("customer_id", sa.String(), nullable=True), sa.Column("occurred_at", TS, nullable=False), sa.Column("quantity", sa.Float(), nullable=False),
       sa.Column("unit", sa.String(), nullable=False, server_default="units"), sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
       sa.Column("state", sa.String(), nullable=False, server_default="active"), sa.Column("payload_hash", sa.String(), nullable=False), sa.Column("batch_id", sa.String(), nullable=False, index=True),
       sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("tenant_id", "source", "event_id", name="uq_workload_event"))
    _t("actuals_policy",
       sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("site_id", sa.String(), primary_key=True), sa.Column("activity", sa.String(), primary_key=True),
       sa.Column("authority", sa.String(), nullable=False), sa.Column("set_by", sa.String(), nullable=False), sa.Column("set_at", TS, nullable=False, server_default=sa.func.now()),
       sa.Column("reason", sa.String(), nullable=False, server_default=""))
    _t("site_forecast_preference",
       sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("site_id", sa.String(), primary_key=True), sa.Column("source", sa.String(), nullable=False, server_default="generated"),
       sa.Column("set_by", sa.String(), nullable=False), sa.Column("set_at", TS, nullable=False, server_default=sa.func.now()))
    for t in TENANT_ONLY:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{t}" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')
    site_expr = f"{TENANT} AND ({WIDE} OR {IN_SCOPE})"
    for t in SITE_KEYED:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{t}" FOR ALL TO tempo_app USING ({site_expr}) WITH CHECK ({site_expr})')
    for t in NO_DELETE:  # raw evidence is kept; undo changes state instead
        op.execute(f'REVOKE DELETE, TRUNCATE ON "{t}" FROM tempo_app')


def downgrade() -> None:
    for t in reversed(TENANT_ONLY + SITE_KEYED):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
    for t in ["site_forecast_preference", "actuals_policy", "workload_event", "supplied_forecast", "import_mapping", "import_row", "import_batch"]:
        op.drop_table(t)
