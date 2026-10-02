"""Native capture — Business Specification §4/§5's "Time & Attendance
(native capture path)" for Standalone mode: Tempo's own PIN/GPS/NFC
clock-in, not an Overlay connector reading Deputy/UKG.

Not §6.1 canonical entities (the Integration Spec has nothing to say about
Standalone capture credentials — it's written entirely from the
Overlay/Prime integration side) and not Maestro operational tables either
(app/models/connectors.py) — these are Tempo-native capture's own
configuration, same tier as WorkerPerformanceProfile/ActivityRoleZoneMap:
Tempo-governed, provisioned by a Tenant Admin, not sourced from a vendor.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkerCredential(Base):
    """A worker's clock-in credential(s). `pin_hash` is an Argon2id hash (unique salt per PIN), never
    the plaintext PIN (app.core.attendance.hash_pin) — the same
    store-a-hash-never-the-secret convention app.core.action_tokens'
    action_token_hash already uses. A PIN is verified against the
    worker the kiosk names (worker number + PIN), never looked up by hash.
    """

    __tablename__ = "worker_credential"
    worker_id: Mapped[str] = mapped_column(String, ForeignKey("worker.worker_id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    pin_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    nfc_tag_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # Abuse controls: consecutive failures lock the credential for a cooling-off period.
    failed_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class SiteGeofence(Base):
    """Optional GPS bounds for a site's clock-in — a site with no row here
    simply skips the geofence check (app.core.attendance.check_geofence),
    it isn't treated as a failure; not every Standalone deployment needs
    GPS-gated clock-in (PIN/NFC alone is a legitimate configuration too).
    """

    __tablename__ = "site_geofence"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    radius_meters: Mapped[float] = mapped_column(Float)


class AttendancePunch(Base):
    """One thing a worker (or a correcting supervisor) did, exactly as received. Append-only: DELETE is revoked."""

    __tablename__ = "attendance_punch"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    worker_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # clock_in | break_start | break_end | clock_out
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    device_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="kiosk")
    note: Mapped[str | None] = mapped_column(String, nullable=True)
    # Where the DEVICE was when the tap happened (a kiosk is shared, so this is the kiosk's position, not the worker's)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_status: Mapped[str] = mapped_column(String, default="not_requested")  # not_requested | passed | outside | no_fence | unavailable | denied


class AttendancePolicy(Base):
    """Explicit per-site rules. Defaults are conservative and visible in the UI, never silently assumed."""

    __tablename__ = "attendance_policy"
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    breaks_paid: Mapped[bool] = mapped_column(default=False)
    rounding_minutes: Mapped[int] = mapped_column(default=0)
    rounding_mode: Mapped[str] = mapped_column(String, default="nearest")
    duplicate_window_seconds: Mapped[int] = mapped_column(default=30)
    late_grace_minutes: Mapped[int] = mapped_column(default=5)
    missing_punch_after_hours: Mapped[float] = mapped_column(Float, default=14)
    excessive_hours: Mapped[float] = mapped_column(Float, default=12)
    location_mode: Mapped[str] = mapped_column(String, default="off")  # off | record | require
    updated_by: Mapped[str] = mapped_column(String, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AttendanceRevision(Base):
    """Every approval, reopening and adjustment of a timesheet, with a snapshot of what it looked like."""

    __tablename__ = "attendance_revision"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    revision: Mapped[int] = mapped_column()
    action: Mapped[str] = mapped_column(String)  # approved | reopened | adjusted
    actor: Mapped[str] = mapped_column(String)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
