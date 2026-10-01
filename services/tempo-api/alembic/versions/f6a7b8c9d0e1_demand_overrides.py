"""Demand overrides (manual, reasoned, expiring forecast adjustments) with tenant RLS.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None
EXPR = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    op.create_table("demand_override",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("activity", sa.String(), nullable=True),
        sa.Column("start_date", sa.String(), nullable=False), sa.Column("end_date", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False), sa.Column("value", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False), sa.Column("origin", sa.String(), nullable=False, server_default="manual"),
        sa.Column("state", sa.String(), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_by", sa.String(), nullable=True), sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(), nullable=True))
    op.execute('ALTER TABLE "demand_override" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "demand_override" FOR ALL TO tempo_app USING ({EXPR}) WITH CHECK ({EXPR})')
    op.execute('REVOKE DELETE, TRUNCATE ON "demand_override" FROM tempo_app')  # never deleted: revoked rows are the history


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "demand_override"')
    op.drop_table("demand_override")
