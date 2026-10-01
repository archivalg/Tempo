"""In-app notifications (per user, deduplicated, never deleted) with tenant RLS.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None
EXPR = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    op.create_table("notification",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("user_id", sa.String(), nullable=False, index=True), sa.Column("kind", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="info"), sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=False, server_default=""), sa.Column("link", sa.String(), nullable=True),
        sa.Column("site_id", sa.String(), nullable=True), sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "user_id", "dedup_key", name="uq_notification_dedup"))
    op.execute('ALTER TABLE "notification" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "notification" FOR ALL TO tempo_app USING ({EXPR}) WITH CHECK ({EXPR})')
    op.execute('REVOKE DELETE, TRUNCATE ON "notification" FROM tempo_app')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "notification"')
    op.drop_table("notification")
