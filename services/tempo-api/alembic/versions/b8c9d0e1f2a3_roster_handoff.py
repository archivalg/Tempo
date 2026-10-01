"""Roster handoff to an external roster of record (Overlay sites), with tenant RLS and no deletes.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None
EXPR = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    op.create_table("roster_handoff",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("version_id", sa.String(), nullable=False, index=True),
        sa.Column("payload_hash", sa.String(), nullable=False), sa.Column("payload", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True), sa.Column("exported_by", sa.String(), nullable=True), sa.Column("file_sha256", sa.String(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True), sa.Column("submitted_by", sa.String(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("vendor_detail", sa.String(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True), sa.Column("confirmed_by", sa.String(), nullable=True),
        sa.Column("confirm_reference", sa.String(), nullable=True), sa.Column("confirm_note", sa.String(), nullable=True),
        sa.UniqueConstraint("tenant_id", "version_id", name="uq_handoff_version"))
    op.execute('ALTER TABLE "roster_handoff" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "roster_handoff" FOR ALL TO tempo_app USING ({EXPR}) WITH CHECK ({EXPR})')
    op.execute('REVOKE DELETE, TRUNCATE ON "roster_handoff" FROM tempo_app')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "roster_handoff"')
    op.drop_table("roster_handoff")
