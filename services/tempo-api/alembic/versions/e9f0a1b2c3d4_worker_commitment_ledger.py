"""Cross-run-type worker commitment ledger (worker_commitment) — lets a committed order_fulfillment
run and a published roster respect the SAME worker reservations at a site without sharing a scheduler.
Order-driven and forecast-driven (named-roster) planning previously had no shared concept of "this
worker's time is already promised"; this closes that gap for committed/published plans only — a draft
plan never reads or writes this table.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "d8e9f0a1b2c3"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"
WIDE = "coalesce(current_setting('app.site_scope', true), '') IN ('', '*')"
IN_SCOPE = "site_id = ANY (string_to_array(current_setting('app.site_scope', true), ','))"
SITE_SCOPED_EXPR = f"{TENANT} AND ({WIDE} OR {IN_SCOPE})"


def upgrade() -> None:
    op.create_table("worker_commitment",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("worker_id", sa.String(), nullable=False, index=True),
        sa.Column("run_id", sa.String(), nullable=False, index=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False), sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("released_at", sa.DateTime(timezone=True), nullable=True))
    op.execute('ALTER TABLE "worker_commitment" ENABLE ROW LEVEL SECURITY')
    # Has a site_id column, so it must be SITE-scoped, not just tenant-scoped (tests/test_rls.py::
    # test_every_site_keyed_table_is_site_scoped_or_deliberately_excluded) — a caller granted only some
    # sites must not see another site's worker commitments even within the same tenant.
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "worker_commitment" FOR ALL TO tempo_app USING ({SITE_SCOPED_EXPR}) WITH CHECK ({SITE_SCOPED_EXPR})')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "worker_commitment"')
    op.drop_table("worker_commitment")
