"""Plans, manual subscriptions and their history (roadmap M6-PLAN, M6-MANUAL).

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None
TENANT = "tenant_id = current_setting('app.tenant_id', true)"
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    plan = op.create_table("plan_definition",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("plan_key", sa.String(), nullable=False, index=True), sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("name", sa.String(), nullable=False), sa.Column("monthly_price_per_site_aud", sa.Float(), nullable=True), sa.Column("entitlements", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"), sa.Column("notes", sa.String(), nullable=False, server_default=""),
        sa.Column("created_by", sa.String(), nullable=True), sa.Column("approved_by", sa.String(), nullable=True), sa.Column("approved_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()), sa.UniqueConstraint("plan_key", "version", name="uq_plan_version"))
    op.create_table("tenant_subscription",
        sa.Column("tenant_id", sa.String(), primary_key=True), sa.Column("plan_key", sa.String(), nullable=False), sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("billing_source", sa.String(), nullable=False), sa.Column("manual_kind", sa.String(), nullable=True), sa.Column("reason", sa.String(), nullable=False, server_default=""),
        sa.Column("reference", sa.String(), nullable=True), sa.Column("licensed_sites", sa.Integer(), nullable=False), sa.Column("worker_band", sa.String(), nullable=False),
        sa.Column("discount_pct", sa.Float(), nullable=False, server_default="0"), sa.Column("entitlements_override", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"), sa.Column("effective_from", TS, nullable=False, server_default=sa.func.now()), sa.Column("expires_at", TS, nullable=True),
        sa.Column("stripe_customer_id", sa.String(), nullable=True), sa.Column("stripe_subscription_id", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=False, server_default=""), sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("billing_source in ('manual','stripe')", name="ck_billing_source"),
        sa.CheckConstraint("billing_source <> 'manual' OR (stripe_customer_id IS NULL AND stripe_subscription_id IS NULL)", name="ck_manual_has_no_stripe_ids"))
    op.create_table("subscription_event",
        sa.Column("id", sa.String(), primary_key=True), sa.Column("tenant_id", sa.String(), nullable=False, index=True), sa.Column("at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("actor", sa.String(), nullable=False), sa.Column("action", sa.String(), nullable=False), sa.Column("reason", sa.String(), nullable=False, server_default=""),
        sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"))
    for t in ("tenant_subscription", "subscription_event"):
        op.execute(f'ALTER TABLE "{t}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY tempo_tenant_isolation ON "{t}" FOR ALL TO tempo_app USING ({TENANT}) WITH CHECK ({TENANT})')
    op.execute('REVOKE DELETE, TRUNCATE ON "subscription_event" FROM tempo_app')
    op.execute('REVOKE DELETE, TRUNCATE ON "plan_definition" FROM tempo_app')
    # Indicative proposals from the roadmap (Arch's notes). DRAFT: prices and the feature matrix still need approval.
    op.bulk_insert(plan, [
        {"id": f"plan-{k}-1", "plan_key": k, "version": 1, "name": n, "monthly_price_per_site_aud": p, "entitlements": {}, "status": "draft",
         "notes": "Indicative proposal; price, workforce allowance and feature matrix are not approved."}
        for k, n, p in (("essentials", "Essentials", 1500.0), ("optimise", "Optimise", 3500.0), ("orchestrate", "Orchestrate", 6500.0), ("network", "Network", None))])


def downgrade() -> None:
    for t in ("subscription_event", "tenant_subscription"):
        op.execute(f'DROP POLICY IF EXISTS tempo_tenant_isolation ON "{t}"')
        op.drop_table(t)
    op.drop_table("plan_definition")
