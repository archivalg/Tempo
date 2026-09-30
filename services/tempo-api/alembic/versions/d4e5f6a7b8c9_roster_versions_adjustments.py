"""Roster versions + events, attendance adjustments, attendance-approval permission (tables with tenant RLS).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None
TABLES = ["roster_version", "roster_event", "attendance_adjustment"]
EXPR = "tenant_id = current_setting('app.tenant_id', true)"


def upgrade() -> None:
    op.create_table("roster_version",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("week_start", sa.String(), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False, server_default="7"), sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("state", sa.String(), nullable=False, server_default="draft"), sa.Column("source", sa.String(), nullable=False, server_default="solver"),
        sa.Column("source_run_id", sa.String(), nullable=True), sa.Column("parent_version_id", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("payload_hash", sa.String(), nullable=True), sa.Column("submitted_by", sa.String(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True), sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True), sa.Column("decision_note", sa.String(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True), sa.Column("published_by", sa.String(), nullable=True),
        sa.Column("reconciliation", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table("roster_event",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("version_id", sa.String(), nullable=False, index=True), sa.Column("at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_user_id", sa.String(), nullable=False), sa.Column("action", sa.String(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table("attendance_adjustment",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("session_id", sa.String(), nullable=False, index=True), sa.Column("site_id", sa.String(), nullable=False, index=True),
        sa.Column("requested_start", sa.DateTime(timezone=True), nullable=False), sa.Column("requested_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(), nullable=False), sa.Column("state", sa.String(), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.String(), nullable=False), sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("decided_by", sa.String(), nullable=True), sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.String(), nullable=True))
    for t in TABLES:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{t}" FOR ALL TO tempo_app USING ({EXPR}) WITH CHECK ({EXPR})')
        op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{t}" TO tempo_app')
    # roster history is an audit trail: events are append-only for the runtime role
    op.execute('REVOKE UPDATE, DELETE, TRUNCATE ON "roster_event" FROM tempo_app')


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
        op.drop_table(t)
