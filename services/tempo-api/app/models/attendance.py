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

from sqlalchemy import DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WorkerCredential(Base):
    """A worker's clock-in credential(s). `pin_hash` is a salted hash, never
    the plaintext PIN (app.core.attendance.hash_pin) — the same
    store-a-hash-never-the-secret convention app.core.action_tokens'
    action_token_hash already uses. Unique per tenant so resolving "who
    just entered this PIN" (clock-in doesn't start from a known
    worker_id — that's the point of a PIN) has exactly one answer.
    """

    __tablename__ = "worker_credential"
    __table_args__ = (UniqueConstraint("tenant_id", "pin_hash", name="uq_worker_credential_tenant_pin"),)

    worker_id: Mapped[str] = mapped_column(String, ForeignKey("worker.worker_id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    pin_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    nfc_tag_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
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
