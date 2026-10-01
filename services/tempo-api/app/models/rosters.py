"""Roster versions (Blueprint §7 roster state machine), events, and attendance adjustments.

A RosterVersion owns its shifts through ShiftAssignment.source_ref = version id. Draft/edited rows stay
status 'proposed'; publication promotes them to 'committed' exactly once and marks the previous
published rows 'superseded'. Every transition writes a RosterEvent (who, what, when).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


ROSTER_STATES = ("draft", "pending_approval", "approved", "publishing", "published", "unknown", "failed", "reconciled", "rejected", "cancelled", "superseded")


class RosterVersion(Base):
    __tablename__ = "roster_version"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("rv"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    week_start: Mapped[str] = mapped_column(String)  # site-local date (YYYY-MM-DD) of the first day
    days: Mapped[int] = mapped_column(Integer, default=7)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String, default="draft")
    source: Mapped[str] = mapped_column(String, default="solver")  # solver | copy_of_published | manual
    source_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)
    payload_hash: Mapped[str | None] = mapped_column(String, nullable=True)  # hash of the shifts as submitted
    submitted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String, nullable=True)
    reconciliation: Mapped[dict] = mapped_column(JSON, default=dict)


class RosterEvent(Base):
    __tablename__ = "roster_event"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("re"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    version_id: Mapped[str] = mapped_column(String, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    actor_user_id: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class AttendanceAdjustment(Base):
    """A supervised correction. The original AttendanceSession is never edited; payable time uses the
    approved adjustment when there is one."""

    __tablename__ = "attendance_adjustment"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("adj"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    requested_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="pending")  # pending | approved | rejected
    requested_by: Mapped[str] = mapped_column(String)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_by: Mapped[str | None] = mapped_column(String, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String, nullable=True)


class DemandOverride(Base):
    """A manual, reasoned, expiring adjustment to the forecast for one site and a run of local dates.

    The statistical forecast is never edited: the override is applied when a forecast run is produced and the run keeps
    the model's own number (`model_point`) next to the adjusted one, so accuracy is always measured on the model.
    """

    __tablename__ = "demand_override"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("dov"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    activity: Mapped[str | None] = mapped_column(String, nullable=True)  # None = every activity
    start_date: Mapped[str] = mapped_column(String)  # site-local, inclusive
    end_date: Mapped[str] = mapped_column(String)
    mode: Mapped[str] = mapped_column(String)  # multiply | set_units (daily total per activity)
    value: Mapped[float] = mapped_column()
    reason: Mapped[str] = mapped_column(String)
    origin: Mapped[str] = mapped_column(String, default="manual")
    state: Mapped[str] = mapped_column(String, default="active")  # active | revoked
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    revoked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class Notification(Base):
    """An in-app notice for one user. Created by workflow events (roster submitted/decided/published, corrections,
    high-severity exceptions); a (user, dedup_key) pair is only ever notified once. Never deleted: read_at is the state."""

    __tablename__ = "notification"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: _id("ntf"))
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String, default="info")  # info | action | urgent
    title: Mapped[str] = mapped_column(String)
    body: Mapped[str] = mapped_column(String, default="")
    link: Mapped[str | None] = mapped_column(String, nullable=True)
    site_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dedup_key: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
