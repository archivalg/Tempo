"""Email-code second factor: a per-user switch and single-use hashed codes.

Revision ID: a9b0c1d2e3f4
Revises: f8a9b0c1d2e3
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("tempo_user", sa.Column("email_mfa_enabled_at", TS, nullable=True))
    op.create_table("email_otp", sa.Column("id", sa.String(), primary_key=True), sa.Column("user_id", sa.String(), sa.ForeignKey("tempo_user.user_id"), nullable=False, index=True),
        sa.Column("purpose", sa.String(), nullable=False), sa.Column("code_hash", sa.String(), nullable=False), sa.Column("expires_at", TS, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("consumed_at", TS, nullable=True), sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()))


def downgrade() -> None:
    op.drop_table("email_otp")
    op.drop_column("tempo_user", "email_mfa_enabled_at")
