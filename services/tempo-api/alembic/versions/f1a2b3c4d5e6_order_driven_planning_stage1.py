"""Order-driven-planning Stage 1: operating calendar, shift templates, shift breaks (site-scoped RLS).

Revision ID: f1a2b3c4d5e6
Revises: a9b0c1d2e3f4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None

TENANT = "tenant_id = current_setting('app.tenant_id', true)"
WIDE = "coalesce(current_setting('app.site_scope', true), '') IN ('', '*')"
IN_SCOPE = "site_id = ANY (string_to_array(current_setting('app.site_scope', true), ','))"
SITE_SCOPED_EXPR = f"{TENANT} AND ({WIDE} OR {IN_SCOPE})"
TENANT_ONLY_EXPR = TENANT  # shift_break has no site_id of its own; it follows its shift_template


def _site_scoped_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{table}" FOR ALL TO tempo_app USING ({SITE_SCOPED_EXPR}) WITH CHECK ({SITE_SCOPED_EXPR})')


def _tenant_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{table}" FOR ALL TO tempo_app USING ({TENANT_ONLY_EXPR}) WITH CHECK ({TENANT_ONLY_EXPR})')


def upgrade() -> None:
    op.create_table("operating_calendar_day",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("weekday", sa.String(), nullable=False),
        sa.Column("is_24h", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("open_time", sa.String(), nullable=True), sa.Column("close_time", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "site_id", "weekday", name="uq_operating_calendar_day"))
    op.create_table("shift_template",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("shift_code", sa.String(), nullable=False),
        sa.Column("start_time", sa.String(), nullable=False), sa.Column("end_time", sa.String(), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("effective_from", sa.Date(), nullable=False), sa.Column("effective_to", sa.Date(), nullable=True))
    op.create_table("shift_break",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("shift_template_id", sa.String(), sa.ForeignKey("shift_template.id"), nullable=False, index=True),
        sa.Column("starts_after_minutes", sa.Integer(), nullable=False), sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("is_paid", sa.Boolean(), nullable=False, server_default=sa.false()))
    for t in ("operating_calendar_day", "shift_template"):
        _site_scoped_rls(t)
    _tenant_rls("shift_break")


def downgrade() -> None:
    for t in ("shift_break", "shift_template", "operating_calendar_day"):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
    op.drop_table("shift_break")
    op.drop_table("shift_template")
    op.drop_table("operating_calendar_day")
