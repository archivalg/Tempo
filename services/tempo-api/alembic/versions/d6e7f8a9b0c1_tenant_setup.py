"""Resumable guided setup state per tenant (roadmap M6-ONBOARD).

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None
TENANT = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    op.create_table("tenant_setup",
        sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("current_step", sa.String(), nullable=False, server_default="sites"),
        sa.Column("attendance_choice", sa.String(), nullable=True), sa.Column("skipped", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("updated_by", sa.String(), nullable=False, server_default=""), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()))
    op.execute('ALTER TABLE "tenant_setup" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "tenant_setup" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "tenant_setup"')
    op.drop_table("tenant_setup")
