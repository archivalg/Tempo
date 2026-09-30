"""Gate 1: kiosk/worker abuse controls, per-PIN salting (drop unique pin hash), tenant registry.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_worker_credential_tenant_pin", "worker_credential", type_="unique")
    op.add_column("worker_credential", sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("worker_credential", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("kiosk_device", sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("kiosk_device", sa.Column("failed_window_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("kiosk_device", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "tenant",
        sa.Column("tenant_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("plan", sa.String(), nullable=False, server_default="pilot"),
        sa.Column("feature_flags", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("writeback_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Platform-registry table: readable by a member tenant (its own row) or in the auth phase.
    op.execute("ALTER TABLE tenant ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tempo_tenant_registry ON tenant FOR ALL TO tempo_app "
        "USING (tenant_id = current_setting('app.tenant_id', true) OR current_setting('app.auth_lookup', true) = 'on') "
        "WITH CHECK (current_setting('app.auth_lookup', true) = 'on')"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON tenant TO tempo_app")
    # Global audit is readable only by the platform (auth-phase) code path; tenants read their own rows.
    op.execute(
        "CREATE POLICY tempo_audit_platform_read ON security_audit_event FOR SELECT TO tempo_app "
        "USING (current_setting('app.auth_lookup', true) = 'on')"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tempo_audit_platform_read ON security_audit_event")
    op.execute("DROP POLICY IF EXISTS tempo_tenant_registry ON tenant")
    op.drop_table("tenant")
    for c in ("locked_until", "failed_window_start", "failed_count"):
        op.drop_column("kiosk_device", c)
    op.drop_column("worker_credential", "locked_until")
    op.drop_column("worker_credential", "failed_attempts")
    op.create_unique_constraint("uq_worker_credential_tenant_pin", "worker_credential", ["tenant_id", "pin_hash"])
