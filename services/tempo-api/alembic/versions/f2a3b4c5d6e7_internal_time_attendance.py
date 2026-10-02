"""Internal time and attendance (roadmap M2): punches, break state, site policy, corrections, timesheet revisions.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None
TENANT = "tenant_id = current_setting('app.tenant_id', true)"
WIDE = "coalesce(current_setting('app.site_scope', true), '') IN ('', '*')"
IN_SCOPE = "site_id = ANY (string_to_array(current_setting('app.site_scope', true), ','))"
SITE_KEYED = ["attendance_punch", "attendance_policy", "attendance_revision"]
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    # session: where it happened, live state, break bookkeeping, and APPROVED adjustments held apart from the original punches
    for col in [
        sa.Column("site_id", sa.String(), nullable=True, index=True),
        sa.Column("state", sa.String(), nullable=False, server_default="working"),
        sa.Column("break_started_at", TS, nullable=True),
        sa.Column("device_id", sa.String(), nullable=True),
        sa.Column("rostered_shift_id", sa.String(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("approved_at", TS, nullable=True),
    ]:
        op.add_column("attendance_session", col)
    # sessions that already ended are closed, those still open keep the default 'working'
    op.execute("UPDATE attendance_session SET state = 'closed' WHERE end_at IS NOT NULL")
    op.execute("UPDATE attendance_session s SET site_id = w.home_site FROM worker w WHERE w.worker_id = s.worker_id AND s.site_id IS NULL")
    op.create_table("attendance_punch",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("session_id", sa.String(), nullable=False, index=True),
        sa.Column("worker_id", sa.String(), nullable=False, index=True), sa.Column("kind", sa.String(), nullable=False),
        sa.Column("at", TS, nullable=False), sa.Column("device_id", sa.String(), nullable=True), sa.Column("source", sa.String(), nullable=False, server_default="kiosk"),
        sa.Column("note", sa.String(), nullable=True))
    op.create_table("attendance_policy",
        sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("site_id", sa.String(), primary_key=True),
        sa.Column("breaks_paid", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("rounding_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rounding_mode", sa.String(), nullable=False, server_default="nearest"),
        sa.Column("duplicate_window_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("late_grace_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("missing_punch_after_hours", sa.Float(), nullable=False, server_default="14"),
        sa.Column("excessive_hours", sa.Float(), nullable=False, server_default="12"),
        sa.Column("updated_by", sa.String(), nullable=False, server_default=""), sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()))
    # corrections reuse attendance_adjustment (already approval-gated): add break minutes, a missing-session kind and the original snapshot
    op.add_column("attendance_adjustment", sa.Column("kind", sa.String(), nullable=False, server_default="amend"))
    op.add_column("attendance_adjustment", sa.Column("worker_id", sa.String(), nullable=True))
    op.add_column("attendance_adjustment", sa.Column("requested_break_minutes", sa.Float(), nullable=True))
    op.add_column("attendance_adjustment", sa.Column("original", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("attendance_adjustment", sa.Column("applied_session_id", sa.String(), nullable=True))
    op.alter_column("attendance_adjustment", "session_id", existing_type=sa.String(), nullable=True)
    op.alter_column("attendance_adjustment", "requested_start", existing_type=sa.DateTime(timezone=True), nullable=True)
    op.execute("UPDATE attendance_adjustment a SET worker_id = s.worker_id FROM attendance_session s WHERE s.id = a.session_id")
    op.execute("CREATE UNIQUE INDEX uq_native_open_session ON attendance_session (tenant_id, worker_id) WHERE state IN ('working','on_break') AND source_system = 'tempo_native'")
    op.execute('REVOKE DELETE, TRUNCATE ON "attendance_adjustment" FROM tempo_app')
    op.create_table("attendance_revision",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True),
        sa.Column("site_id", sa.String(), nullable=False, index=True), sa.Column("session_id", sa.String(), nullable=False, index=True),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("action", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False), sa.Column("at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("reason", sa.String(), nullable=True), sa.Column("snapshot", sa.JSON(), nullable=False, server_default="{}"))
    site_expr = f"{TENANT} AND ({WIDE} OR {IN_SCOPE})"
    for t in SITE_KEYED:
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{t}" FOR ALL TO tempo_app USING ({site_expr}) WITH CHECK ({site_expr})')
    # sessions now carry a site: imported/connector rows that arrive without one get their worker's home site, and the site policy applies like every other site table
    op.execute("""CREATE FUNCTION attendance_session_fill_site() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.site_id IS NULL THEN SELECT home_site INTO NEW.site_id FROM worker WHERE worker_id = NEW.worker_id; END IF;
  RETURN NEW;
END $$""")
    op.execute("CREATE TRIGGER attendance_session_fill_site BEFORE INSERT ON attendance_session FOR EACH ROW EXECUTE FUNCTION attendance_session_fill_site()")
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "attendance_session"')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "attendance_session" FOR ALL TO tempo_app USING ({site_expr}) WITH CHECK ({site_expr})')
    for t in ["attendance_punch", "attendance_revision"]:  # original evidence and the decision trail are never deleted
        op.execute(f'REVOKE DELETE, TRUNCATE ON "{t}" FROM tempo_app')


def downgrade() -> None:
    op.execute('DROP POLICY IF EXISTS tempo_tenant_isolation ON "attendance_session"')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "attendance_session" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')
    op.execute("DROP TRIGGER IF EXISTS attendance_session_fill_site ON attendance_session")
    op.execute("DROP FUNCTION IF EXISTS attendance_session_fill_site()")
    op.execute("DROP INDEX IF EXISTS uq_native_open_session")
    for c in ["applied_session_id", "original", "requested_break_minutes", "worker_id", "kind"]:
        op.drop_column("attendance_adjustment", c)
    for t in reversed(SITE_KEYED):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
        op.drop_table(t)
    for c in ["approved_at", "approved_by", "revision",
              "rostered_shift_id", "device_id", "break_started_at", "state", "site_id"]:
        op.drop_column("attendance_session", c)
