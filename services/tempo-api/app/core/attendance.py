"""Native capture — Business Spec §4/§5's Standalone "Time & Attendance
(native capture path)": PIN/GPS/NFC clock-in writing directly to Tempo's
own canonical tables, no Maestro connector involved. Same
tempo_native `source_system` every other directly-seeded canonical row
uses.

Scope reductions:
- PIN/NFC are the only two identity methods; biometric (also named in the
  Business Spec) needs a hardware integration this codebase can't provide.
- One open `AttendanceSession` per worker at a time — a second clock-in
  before clocking out is rejected, not treated as an implicit clock-out
  (a real kiosk usually asks "did you mean to clock out?" rather than
  silently closing the previous session).
- A clock-in that doesn't match any `ShiftAssignment` for that worker/time
  still succeeds — real attendance has exceptions — but is flagged in the
  response as unscheduled, a starting point for the Business Spec's
  "every exception visible... within 15 minutes" requirement, not a full
  exception/alerting system.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AttendanceStateConflict, AuthInvalid, GeofenceViolation
from app.models.attendance import SiteGeofence, WorkerCredential
from app.models.canonical import AttendanceSession, ShiftAssignment, Worker

SOURCE_SYSTEM = "tempo_native"
EARTH_RADIUS_METERS = 6_371_000.0


def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def to_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return EARTH_RADIUS_METERS * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def resolve_worker_by_pin(db: Session, tenant_id: str, pin: str) -> Worker:
    credential = db.scalar(
        select(WorkerCredential).where(WorkerCredential.tenant_id == tenant_id).where(WorkerCredential.pin_hash == hash_pin(pin))
    )
    if credential is None:
        raise AuthInvalid("PIN not recognised for this tenant")
    worker = db.get(Worker, credential.worker_id)
    if worker is None or worker.status != "active":
        raise AuthInvalid("worker is not active")
    return worker


def resolve_worker_by_nfc(db: Session, tenant_id: str, nfc_tag_id: str) -> Worker:
    credential = db.scalar(
        select(WorkerCredential).where(WorkerCredential.tenant_id == tenant_id).where(WorkerCredential.nfc_tag_id == nfc_tag_id)
    )
    if credential is None:
        raise AuthInvalid("NFC tag not recognised for this tenant")
    worker = db.get(Worker, credential.worker_id)
    if worker is None or worker.status != "active":
        raise AuthInvalid("worker is not active")
    return worker


def check_geofence(db: Session, tenant_id: str, site_id: str, latitude: float, longitude: float) -> str:
    """Returns "passed" or "skipped" (no geofence configured for this
    site); raises GeofenceViolation if configured and out of bounds.
    """
    geofence = db.get(SiteGeofence, (tenant_id, site_id))
    if geofence is None:
        return "skipped"
    distance = haversine_meters(latitude, longitude, geofence.latitude, geofence.longitude)
    if distance > geofence.radius_meters:
        raise GeofenceViolation(f"clock-in {distance:.0f}m from site '{site_id}', outside its {geofence.radius_meters:.0f}m geofence")
    return "passed"


def _open_session(db: Session, tenant_id: str, worker_id: str) -> AttendanceSession | None:
    return db.scalar(
        select(AttendanceSession)
        .where(AttendanceSession.tenant_id == tenant_id)
        .where(AttendanceSession.worker_id == worker_id)
        .where(AttendanceSession.end_at.is_(None))
    )


def _matches_a_rostered_shift(db: Session, tenant_id: str, worker_id: str, at: datetime) -> bool:
    rows = db.scalars(
        select(ShiftAssignment)
        .where(ShiftAssignment.tenant_id == tenant_id)
        .where(ShiftAssignment.worker_id == worker_id)
        .where(ShiftAssignment.status == "committed")
    ).all()
    return any(to_aware(row.start_at) <= at <= to_aware(row.end_at) for row in rows)


@dataclass
class ClockInResult:
    session: AttendanceSession
    geofence_status: str
    matched_rostered_shift: bool


def clock_in(
    db: Session,
    tenant_id: str,
    site_id: str,
    worker: Worker,
    geofence_status: str = "skipped",
) -> ClockInResult:
    if _open_session(db, tenant_id, worker.worker_id) is not None:
        raise AttendanceStateConflict(f"worker '{worker.worker_id}' already has an open attendance session")

    now = _now()
    session = AttendanceSession(
        tenant_id=tenant_id, worker_id=worker.worker_id, start_at=now, end_at=None,
        approval="pending", source_system=SOURCE_SYSTEM,
    )
    db.add(session)
    db.flush()
    matched = _matches_a_rostered_shift(db, tenant_id, worker.worker_id, now)
    return ClockInResult(session=session, geofence_status=geofence_status, matched_rostered_shift=matched)


def clock_out(db: Session, tenant_id: str, worker: Worker) -> AttendanceSession:
    session = _open_session(db, tenant_id, worker.worker_id)
    if session is None:
        raise AttendanceStateConflict(f"worker '{worker.worker_id}' has no open attendance session to close")
    session.end_at = _now()
    db.flush()
    return session
