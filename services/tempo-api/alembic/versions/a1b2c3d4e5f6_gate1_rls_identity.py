"""Gate 1: PostgreSQL RLS, identity columns, platform admin, kiosk enrolment, append-only audit.

Revision ID: a1b2c3d4e5f6
Revises: 881bb55c3809
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "881bb55c3809"
branch_labels = None
depends_on = None

# Identity tables the principal-resolution phase must read across tenants
# (membership/grants/devices/clients/support grants): extra SELECT-only policy.
AUTH_READABLE = [
    "tenant_membership", "user_role_assignment", "user_site_grant", "user_customer_grant",
    "user_provider_grant", "kiosk_device", "service_client", "privileged_support_grant",
]
APPEND_ONLY = ["security_audit_event", "audit_record", "event_record"]
TENANT_EXPR = "tenant_id = current_setting('app.tenant_id', true)"
AUTH_EXPR = "current_setting('app.auth_lookup', true) = 'on'"


def _tenant_tables(conn):
    rows = conn.execute(sa.text(
        "SELECT table_name FROM information_schema.columns "
        "WHERE table_schema='public' AND column_name='tenant_id' AND table_name <> 'alembic_version' ORDER BY 1"
    ))
    return [r[0] for r in rows]


def upgrade() -> None:
    conn = op.get_bind()
    op.add_column("tempo_user", sa.Column("email", sa.String(), nullable=True))
    op.add_column("tempo_user", sa.Column("display_name", sa.String(), nullable=True))
    op.create_index("ix_tempo_user_email", "tempo_user", ["email"])
    op.add_column("user_session", sa.Column("mfa_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_session", sa.Column("auth_method", sa.String(), nullable=False, server_default="oidc"))
    for col in [("name", sa.String()), ("enrolment_code_digest", sa.String()), ("created_by", sa.String())]:
        op.add_column("kiosk_device", sa.Column(col[0], col[1], nullable=True))
    for col in ("enrolment_expires_at", "enrolled_at", "disabled_at"):
        op.add_column("kiosk_device", sa.Column(col, sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "platform_admin",
        sa.Column("user_id", sa.String(), sa.ForeignKey("tempo_user.user_id"), primary_key=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )

    tables = _tenant_tables(conn)
    for t in tables:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY tempo_tenant_isolation ON "{t}" FOR ALL TO tempo_app '
            f"USING ({TENANT_EXPR}) WITH CHECK ({TENANT_EXPR})"
        )
    for t in AUTH_READABLE:
        op.execute(f'CREATE POLICY tempo_auth_lookup ON "{t}" FOR SELECT TO tempo_app USING ({AUTH_EXPR})')

    # Login/denial events happen before any tenant is known (tenant_id may be NULL): the auth
    # phase may INSERT them. They are still only readable through the tenant policy.
    op.execute(f'CREATE POLICY tempo_audit_auth_insert ON security_audit_event FOR INSERT TO tempo_app WITH CHECK ({AUTH_EXPR})')

    # tempo_user: visible during auth lookup, or to a tenant that has a membership for it.
    op.execute('ALTER TABLE tempo_user ENABLE ROW LEVEL SECURITY')
    op.execute(
        f"CREATE POLICY tempo_user_access ON tempo_user FOR ALL TO tempo_app USING ({AUTH_EXPR} OR EXISTS "
        "(SELECT 1 FROM tenant_membership m WHERE m.user_id = tempo_user.user_id "
        f"AND m.{TENANT_EXPR})) WITH CHECK ({AUTH_EXPR})"
    )
    # Sessions and platform admins are only ever touched by the auth module.
    for t in ("user_session", "platform_admin"):
        op.execute(f'ALTER TABLE {t} ENABLE ROW LEVEL SECURITY')
        op.execute(f"CREATE POLICY tempo_auth_only ON {t} FOR ALL TO tempo_app USING ({AUTH_EXPR}) WITH CHECK ({AUTH_EXPR})")
    # Membership writes (tenant admins) still pass through the tenant policy above.

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tempo_app")
    op.execute("REVOKE ALL ON alembic_version FROM tempo_app")
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tempo_app")
    for t in APPEND_ONLY:
        op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON "{t}" FROM tempo_app')


def downgrade() -> None:
    conn = op.get_bind()
    for t in ("platform_admin", "user_session"):
        op.execute(f"DROP POLICY IF EXISTS tempo_auth_only ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tempo_audit_auth_insert ON security_audit_event")
    op.execute("DROP POLICY IF EXISTS tempo_user_access ON tempo_user")
    op.execute("ALTER TABLE tempo_user DISABLE ROW LEVEL SECURITY")
    for t in AUTH_READABLE:
        op.execute(f'DROP POLICY IF EXISTS tempo_auth_lookup ON "{t}"')
    for t in _tenant_tables(conn):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
        op.execute(f'ALTER TABLE "{t}" DISABLE ROW LEVEL SECURITY')
    op.drop_table("platform_admin")
    for col in ("disabled_at", "enrolled_at", "enrolment_expires_at", "created_by", "enrolment_code_digest", "name"):
        op.drop_column("kiosk_device", col)
    op.drop_column("user_session", "auth_method")
    op.drop_column("user_session", "mfa_verified_at")
    op.drop_index("ix_tempo_user_email", "tempo_user")
    op.drop_column("tempo_user", "display_name")
    op.drop_column("tempo_user", "email")
