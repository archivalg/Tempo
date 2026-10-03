"""Mobile foundation: employee links, shift changes, offers, leave, notification preferences, push devices, jobs and deliveries, SMS usage, kiosk QR.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None
TS = sa.DateTime(timezone=True)
TENANT = "tenant_id = current_setting('app.tenant_id', true)"
WIDE = "coalesce(current_setting('app.site_scope', true), '') IN ('', '*')"
IN_SCOPE = "site_id = ANY (string_to_array(current_setting('app.site_scope', true), ','))"
SITE_KEYED = ["shift_change_event", "shift_offer", "shift_offer_recipient", "leave_request"]
TENANT_ONLY = ["worker_user_link", "notification_preference", "push_device", "notification_job", "push_delivery", "tenant_messaging", "sms_usage", "kiosk_qr_nonce"]
NO_DELETE = ["shift_change_event", "shift_offer", "shift_offer_recipient", "leave_request", "notification_job", "push_delivery", "sms_usage"]


def _tid():
    return sa.Column("tenant_id", sa.String(), nullable=False, index=True)


def upgrade() -> None:
    op.add_column("shift_assignment", sa.Column("break_minutes", sa.Integer(), nullable=True))
    op.add_column("shift_assignment", sa.Column("instructions", sa.String(), nullable=True))
    op.add_column("kiosk_device", sa.Column("client_info", sa.JSON(), nullable=True))
    op.create_table("worker_user_link", sa.Column("id", sa.String(), primary_key=True), _tid(), sa.Column("user_id", sa.String(), nullable=False, index=True),
        sa.Column("worker_id", sa.String(), nullable=False, index=True), sa.Column("linked_by", sa.String(), nullable=False), sa.Column("linked_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "worker_id", name="uq_link_worker"), sa.UniqueConstraint("tenant_id", "user_id", name="uq_link_user"))
    op.create_table("shift_change_event", sa.Column("id", sa.String(), primary_key=True), _tid(), sa.Column("site_id", sa.String(), nullable=False, index=True),
        sa.Column("worker_id", sa.String(), nullable=False, index=True), sa.Column("shift_id", sa.String(), nullable=True), sa.Column("kind", sa.String(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=True), sa.Column("after", sa.JSON(), nullable=True), sa.Column("source_ref", sa.String(), nullable=True),
        sa.Column("at", TS, nullable=False, server_default=sa.func.now()), sa.Column("seen_at", TS, nullable=True))
    op.create_table("shift_offer", sa.Column("id", sa.String(), primary_key=True), _tid(), sa.Column("site_id", sa.String(), nullable=False, index=True),
        sa.Column("role", sa.String(), nullable=False), sa.Column("zone", sa.String(), nullable=False), sa.Column("start_at", TS, nullable=False), sa.Column("end_at", TS, nullable=False),
        sa.Column("break_minutes", sa.Integer(), nullable=True), sa.Column("instructions", sa.String(), nullable=True), sa.Column("status", sa.String(), nullable=False, server_default="open"),
        sa.Column("auto_confirm", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("expires_at", TS, nullable=True), sa.Column("accepted_worker_id", sa.String(), nullable=True),
        sa.Column("assignment_id", sa.String(), nullable=True), sa.Column("created_by", sa.String(), nullable=False), sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("decided_by", sa.String(), nullable=True), sa.Column("decided_at", TS, nullable=True), sa.Column("decision_note", sa.String(), nullable=True))
    op.create_table("shift_offer_recipient", sa.Column("offer_id", sa.String(), primary_key=True), sa.Column("worker_id", sa.String(), primary_key=True), _tid(),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("response", sa.String(), nullable=False, server_default="pending"),
        sa.Column("responded_at", TS, nullable=True), sa.Column("note", sa.String(), nullable=True))
    op.create_table("leave_request", sa.Column("id", sa.String(), primary_key=True), _tid(), sa.Column("site_id", sa.String(), nullable=False, index=True),
        sa.Column("worker_id", sa.String(), nullable=False, index=True), sa.Column("kind", sa.String(), nullable=False), sa.Column("start_date", sa.Date(), nullable=False), sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("reason", sa.String(), nullable=True), sa.Column("status", sa.String(), nullable=False, server_default="pending"), sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("decided_by", sa.String(), nullable=True), sa.Column("decided_at", TS, nullable=True), sa.Column("decision_note", sa.String(), nullable=True))
    op.create_table("notification_preference", sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("user_id", sa.String(), primary_key=True),
        *[sa.Column(c, sa.Boolean(), nullable=False, server_default=sa.true()) for c in ("push_enabled", "roster_published", "shift_changes", "offers", "reminders", "decisions")],
        sa.Column("reminder_lead_minutes", sa.Integer(), nullable=False, server_default="60"), sa.Column("sms_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sms_number", sa.String(), nullable=True), sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()))
    op.create_table("push_device", sa.Column("id", sa.String(), primary_key=True), _tid(), sa.Column("user_id", sa.String(), nullable=False, index=True), sa.Column("platform", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False, server_default="expo"), sa.Column("token", sa.String(), nullable=False), sa.Column("app_version", sa.String(), nullable=True), sa.Column("label", sa.String(), nullable=True),
        sa.Column("registered_at", TS, nullable=False, server_default=sa.func.now()), sa.Column("last_seen_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", TS, nullable=True), sa.Column("invalid_at", TS, nullable=True), sa.Column("invalid_reason", sa.String(), nullable=True), sa.UniqueConstraint("tenant_id", "token", name="uq_push_token"))
    op.create_table("notification_job", sa.Column("id", sa.String(), primary_key=True), _tid(), sa.Column("user_id", sa.String(), nullable=False, index=True), sa.Column("kind", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False), sa.Column("dedup_key", sa.String(), nullable=False), sa.Column("notification_id", sa.String(), nullable=True), sa.Column("run_at", TS, nullable=False, index=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"), sa.Column("urgent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()), sa.Column("processed_at", TS, nullable=True), sa.UniqueConstraint("tenant_id", "dedup_key", name="uq_job_dedup"))
    op.create_table("push_delivery", sa.Column("id", sa.String(), primary_key=True), _tid(), sa.Column("job_id", sa.String(), nullable=False, index=True), sa.Column("notification_id", sa.String(), nullable=True, index=True),
        sa.Column("device_id", sa.String(), nullable=False, index=True), sa.Column("status", sa.String(), nullable=False), sa.Column("provider", sa.String(), nullable=False), sa.Column("provider_ref", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True), sa.Column("attempted_at", TS, nullable=False, server_default=sa.func.now()), sa.Column("receipt_status", sa.String(), nullable=True),
        sa.Column("receipt_checked_at", TS, nullable=True), sa.Column("acknowledged_at", TS, nullable=True))
    op.create_table("tenant_messaging", sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("push_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sms_enabled", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("sms_monthly_cap", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("default_reminder_lead_minutes", sa.Integer(), nullable=False, server_default="60"), sa.Column("updated_by", sa.String(), nullable=False, server_default=""),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()))
    op.create_table("sms_usage", sa.Column("id", sa.String(), primary_key=True), _tid(), sa.Column("user_id", sa.String(), nullable=False), sa.Column("notification_id", sa.String(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False), sa.Column("status", sa.String(), nullable=False), sa.Column("segments", sa.Integer(), nullable=False, server_default="1"), sa.Column("at", TS, nullable=False, server_default=sa.func.now()))
    op.create_table("kiosk_qr_nonce", sa.Column("nonce", sa.String(), primary_key=True), _tid(), sa.Column("worker_id", sa.String(), nullable=False), sa.Column("expires_at", TS, nullable=False), sa.Column("used_at", TS, nullable=True))
    for t in TENANT_ONLY:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{t}" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')
    expr = f"{TENANT} AND ({WIDE} OR {IN_SCOPE})"
    for t in SITE_KEYED:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{t}" FOR ALL TO tempo_app USING ({expr}) WITH CHECK ({expr})')
    for t in NO_DELETE:
        op.execute(f'REVOKE DELETE, TRUNCATE ON "{t}" FROM tempo_app')


def downgrade() -> None:
    for t in reversed(TENANT_ONLY + SITE_KEYED):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
        op.drop_table(t)
    op.drop_column("kiosk_device", "client_info")
    op.drop_column("shift_assignment", "instructions")
    op.drop_column("shift_assignment", "break_minutes")
