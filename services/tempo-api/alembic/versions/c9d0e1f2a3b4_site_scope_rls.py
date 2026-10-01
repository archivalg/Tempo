"""Site-level row security: site-keyed tables also honour the caller's granted sites (app.site_scope).

Unset / empty / '*' means tenant-wide (trusted internal paths only); '!none' (no grants) matches nothing.
Deliberately excluded: user_site_grant and tenant_scope (tenant admin user management reads across sites) and optimisation_run_site
(runs.py proves a run is in scope by checking that ALL of its site rows are granted — hiding rows would turn that into a fail-open).

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None

TABLES = ["action_request", "activity_role_zone_map", "attendance_adjustment", "data_source_status", "demand_bucket", "demand_override", "exception_case",
          "maestro_connection", "roster_handoff", "roster_version", "site", "site_geofence", "source_version_watermark", "zone", "zone_backlog"]
NULLABLE = ["notification"]  # site_id may be NULL (tenant-wide notice)
TENANT = "tenant_id = current_setting('app.tenant_id', true)"
WIDE = "coalesce(current_setting('app.site_scope', true), '') IN ('', '*')"
IN_SCOPE = "site_id = ANY (string_to_array(current_setting('app.site_scope', true), ','))"


def _swap(table: str, expr: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{table}"')
    op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{table}" FOR ALL TO tempo_app USING ({expr}) WITH CHECK ({expr})')


def upgrade() -> None:
    for t in TABLES:
        _swap(t, f"{TENANT} AND ({WIDE} OR {IN_SCOPE})")
    for t in NULLABLE:
        _swap(t, f"{TENANT} AND ({WIDE} OR site_id IS NULL OR {IN_SCOPE})")


def downgrade() -> None:
    for t in TABLES + NULLABLE:
        _swap(t, TENANT)
