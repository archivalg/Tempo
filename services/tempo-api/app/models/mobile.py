"""Employee app, shift offers, leave, push notifications and their jobs (mobile foundation).

Rules baked into the shapes:
* An employee account is a normal user with the 'employee' role (permission labour.self only) linked to exactly one worker.
* A push delivery row records what the PROVIDER said (accepted / rejected / unregistered). 'Delivered' is never inferred from acceptance;
  only a provider receipt or the app's own acknowledgement sets those fields.
* Jobs are unique per (tenant, dedup_key), so a retry can never schedule the same reminder or push twice.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:20]}" if prefix else str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkerUserLink(Base):
    __tablename__ = "worker_user_link"
    __table_args__ = (UniqueConstraint("tenant_id", "worker_id", name="uq_link_worker"), UniqueConstraint("tenant_id", "user_id", name="uq_link_user"))
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, index=True)
    linked_by: Mapped[str] = mapped_column(String)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ShiftChangeEvent(Base):
    """What a published roster change meant for one employee: a shift added, changed or cancelled. The employee's 'changes' list reads this."""
    __tablename__ = "shift_change_event"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, index=True)
    shift_id: Mapped[str | None] = mapped_column(String, nullable=True)
    kind: Mapped[str] = mapped_column(String)          # added | changed | cancelled
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)   # roster version or offer that caused it
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ShiftOffer(Base):
    """A shift a manager offers to chosen employees. First acceptance holds it; the manager confirms (unless auto_confirm and nothing conflicts)."""
    __tablename__ = "shift_offer"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    zone: Mapped[str] = mapped_column(String)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    break_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    instructions: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")   # open | pending_confirmation | filled | cancelled | expired
    auto_confirm: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    assignment_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String, nullable=True)


class ShiftOfferRecipient(Base):
    __tablename__ = "shift_offer_recipient"
    offer_id: Mapped[str] = mapped_column(String, primary_key=True)
    worker_id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    response: Mapped[str] = mapped_column(String, default="pending")   # pending | accepted | declined | needs_reconfirmation | not_taken | rejected_by_manager
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String, nullable=True)


class LeaveRequest(Base):
    __tablename__ = "leave_request"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)                           # annual | personal | unpaid | other
    start_date: Mapped[date] = mapped_column(Date)                      # site-local dates, inclusive
    end_date: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")       # pending | approved | rejected | cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String, nullable=True)


class NotificationPreference(Base):
    __tablename__ = "notification_preference"
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    roster_published: Mapped[bool] = mapped_column(Boolean, default=True)
    shift_changes: Mapped[bool] = mapped_column(Boolean, default=True)
    offers: Mapped[bool] = mapped_column(Boolean, default=True)
    reminders: Mapped[bool] = mapped_column(Boolean, default=True)
    decisions: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_lead_minutes: Mapped[int] = mapped_column(Integer, default=60)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_number: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PushDevice(Base):
    __tablename__ = "push_device"
    __table_args__ = (UniqueConstraint("tenant_id", "token", name="uq_push_token"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    platform: Mapped[str] = mapped_column(String)                       # ios | android
    provider: Mapped[str] = mapped_column(String, default="expo")
    token: Mapped[str] = mapped_column(String)
    app_version: Mapped[str | None] = mapped_column(String, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalid_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class NotificationJob(Base):
    __tablename__ = "notification_job"
    __table_args__ = (UniqueConstraint("tenant_id", "dedup_key", name="uq_job_dedup"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)                           # push | reminder
    category: Mapped[str] = mapped_column(String)                       # roster_published | shift_changes | offers | reminders | decisions
    dedup_key: Mapped[str] = mapped_column(String)
    notification_id: Mapped[str | None] = mapped_column(String, nullable=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String, default="pending")        # pending | done | skipped | failed | cancelled
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PushDelivery(Base):
    __tablename__ = "push_delivery"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    job_id: Mapped[str] = mapped_column(String, index=True)
    notification_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    device_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String)                         # accepted | rejected | failed | device_unregistered
    provider: Mapped[str] = mapped_column(String)
    provider_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    receipt_status: Mapped[str | None] = mapped_column(String, nullable=True)   # provider receipt: ok | error — still not proof the person saw it
    receipt_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)   # the app itself reported receiving or opening it


class TenantMessaging(Base):
    __tablename__ = "tenant_messaging"
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    push_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sms_monthly_cap: Mapped[int] = mapped_column(Integer, default=0)
    default_reminder_lead_minutes: Mapped[int] = mapped_column(Integer, default=60)
    updated_by: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SmsUsage(Base):
    __tablename__ = "sms_usage"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_id)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String)
    notification_id: Mapped[str | None] = mapped_column(String, nullable=True)
    provider: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)                         # sent | blocked_cap | blocked_disabled | blocked_optout | failed
    segments: Mapped[int] = mapped_column(Integer, default=1)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KioskQrNonce(Base):
    """Single-use record for a rotating QR identification token shown in the employee app."""
    __tablename__ = "kiosk_qr_nonce"
    nonce: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
