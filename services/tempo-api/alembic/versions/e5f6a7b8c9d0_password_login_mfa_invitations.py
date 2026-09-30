"""Password sign-in (Argon2id hash, lockout), TOTP MFA columns, one-time invitations.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tempo_user", sa.Column("username", sa.String(), nullable=True))
    op.create_index("ix_tempo_user_username", "tempo_user", ["username"], unique=True)
    op.add_column("tempo_user", sa.Column("password_hash", sa.String(), nullable=True))
    op.add_column("tempo_user", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tempo_user", sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tempo_user", sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tempo_user", sa.Column("totp_secret_enc", sa.String(), nullable=True))
    op.add_column("tempo_user", sa.Column("totp_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tempo_user", sa.Column("totp_last_step", sa.BigInteger(), nullable=False, server_default="0"))
    op.create_table(
        "user_invitation",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("tempo_user.user_id"), nullable=False, index=True),
        sa.Column("token_digest", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("purpose", sa.String(), nullable=False, server_default="invite"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Like sessions: only the auth code path (auth-lookup phase) may touch invitations.
    op.execute("ALTER TABLE user_invitation ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tempo_auth_only ON user_invitation FOR ALL TO tempo_app "
               "USING (current_setting('app.auth_lookup', true) = 'on') WITH CHECK (current_setting('app.auth_lookup', true) = 'on')")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON user_invitation TO tempo_app")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tempo_auth_only ON user_invitation")
    op.drop_table("user_invitation")
    for c in ("totp_last_step", "totp_enabled_at", "totp_secret_enc", "locked_until", "failed_logins", "password_changed_at", "password_hash"):
        op.drop_column("tempo_user", c)
    op.drop_index("ix_tempo_user_username", "tempo_user")
    op.drop_column("tempo_user", "username")
