"""Commercial model (roadmap M6-PLAN / M6-MANUAL): versioned plan definitions, one subscription record per tenant, and its history.

Prices here are indicative proposals until a platform admin approves a plan version. A manual tenant never has a Stripe customer or
subscription ID; the billing source is explicit and Stripe events can only touch rows whose source is 'stripe'."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PlanDefinition(Base):
    __tablename__ = "plan_definition"
    __table_args__ = (UniqueConstraint("plan_key", "version", name="uq_plan_version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    plan_key: Mapped[str] = mapped_column(String, index=True)       # essentials | optimise | orchestrate | network
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String)
    monthly_price_per_site_aud: Mapped[float | None] = mapped_column(Float, nullable=True)   # None = custom
    entitlements: Mapped[dict] = mapped_column(JSON, default=dict)    # feature flags; empty until the feature matrix is agreed
    status: Mapped[str] = mapped_column(String, default="draft")      # draft | approved | retired
    notes: Mapped[str] = mapped_column(String, default="")
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TenantSubscription(Base):
    __tablename__ = "tenant_subscription"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    plan_key: Mapped[str] = mapped_column(String)
    plan_version: Mapped[int] = mapped_column(Integer)
    billing_source: Mapped[str] = mapped_column(String)               # manual | stripe
    manual_kind: Mapped[str | None] = mapped_column(String, nullable=True)   # contract | pilot | demo | complimentary
    reason: Mapped[str] = mapped_column(String, default="")
    reference: Mapped[str | None] = mapped_column(String, nullable=True)
    licensed_sites: Mapped[int] = mapped_column(Integer)
    worker_band: Mapped[str] = mapped_column(String)                   # 250 | 500 | 1000 | 1000+
    discount_pct: Mapped[float] = mapped_column(Float, default=0)
    entitlements_override: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String, default="active")      # active | suspended | expired
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_by: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SubscriptionEvent(Base):
    """History of every commercial change. Append-only."""

    __tablename__ = "subscription_event"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String, default="")
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


# The indicative catalogue the migration seeds (kept here so tests can restore it after the per-test truncate).
DEFAULT_PLANS = [("essentials", "Essentials", 1500.0), ("optimise", "Optimise", 3500.0), ("orchestrate", "Orchestrate", 6500.0), ("network", "Network", None)]


class TenantSetup(Base):
    """Where a tenant is in guided setup, so it can be resumed from any device. Which steps are DONE is always read from the real data."""

    __tablename__ = "tenant_setup"
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    current_step: Mapped[str] = mapped_column(String, default="sites")
    attendance_choice: Mapped[str | None] = mapped_column(String, nullable=True)   # tempo_kiosk | external | later
    skipped: Mapped[list] = mapped_column(JSON, default=list)
    updated_by: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SmtpConfig(Base):
    """The platform's outgoing email account (one row). Managed by platform admins; the password is stored encrypted and is never returned by any API."""

    __tablename__ = "smtp_config"
    id: Mapped[str] = mapped_column(String, primary_key=True, default="default")
    enabled: Mapped[bool] = mapped_column(default=False)
    host: Mapped[str] = mapped_column(String, default="")
    port: Mapped[int] = mapped_column(Integer, default=587)
    security: Mapped[str] = mapped_column(String, default="starttls")   # starttls | ssl | none
    username: Mapped[str] = mapped_column(String, default="")
    password_enc: Mapped[str | None] = mapped_column(String, nullable=True)
    from_email: Mapped[str] = mapped_column(String, default="")
    from_name: Mapped[str] = mapped_column(String, default="Tempo")
    updated_by: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(nullable=True)
    last_test_detail: Mapped[str | None] = mapped_column(String, nullable=True)


class EmailMessage(Base):
    """What was sent, to whom and what happened. The BODY is never stored (invitation emails carry one-time links)."""

    __tablename__ = "email_message"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    to_address: Mapped[str] = mapped_column(String)
    subject: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)                            # invitation | password_reset | test
    status: Mapped[str] = mapped_column(String)                          # sent | failed | not_configured
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
