"""Platform SMTP configuration (encrypted password) and an email log without bodies.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table("smtp_config", sa.Column("id", sa.String(), primary_key=True), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("host", sa.String(), nullable=False, server_default=""), sa.Column("port", sa.Integer(), nullable=False, server_default="587"), sa.Column("security", sa.String(), nullable=False, server_default="starttls"),
        sa.Column("username", sa.String(), nullable=False, server_default=""), sa.Column("password_enc", sa.String(), nullable=True), sa.Column("from_email", sa.String(), nullable=False, server_default=""),
        sa.Column("from_name", sa.String(), nullable=False, server_default="Tempo"), sa.Column("updated_by", sa.String(), nullable=False, server_default=""), sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("last_test_at", TS, nullable=True), sa.Column("last_test_ok", sa.Boolean(), nullable=True), sa.Column("last_test_detail", sa.String(), nullable=True))
    op.create_table("email_message", sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=True, index=True), sa.Column("to_address", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False), sa.Column("kind", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True), sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()))
    # The log carries an optional tenant: a tenant-bound session can only write/see its own rows; the platform (auth-phase) path sees all, including platform-level rows with no tenant.
    op.execute('ALTER TABLE "email_message" ENABLE ROW LEVEL SECURITY')
    op.execute("CREATE POLICY tempo_tenant_isolation ON \"email_message\" FOR ALL TO tempo_app "
               "USING (tenant_id = current_setting('app.tenant_id', true) OR current_setting('app.auth_lookup', true) = 'on') "
               "WITH CHECK (tenant_id IS NULL OR tenant_id = current_setting('app.tenant_id', true) OR current_setting('app.auth_lookup', true) = 'on')")
    op.execute('REVOKE DELETE, TRUNCATE ON "email_message" FROM tempo_app')


def downgrade() -> None:
    op.drop_table("email_message")
    op.drop_table("smtp_config")
