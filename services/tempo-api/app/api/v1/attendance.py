"""Native capture endpoints — Business Spec §4/§5's Standalone "Time &
Attendance (native capture path)". See app/core/attendance.py's docstring
for scope reductions (PIN/NFC only, one open session per worker, no
biometric hardware integration).

Clock-in/out deliberately carry no §5.2 permission gate beyond tenant/site
scope: a physical kiosk isn't an RBAC principal the way a console user is
— the PIN or NFC tag itself is the authentication, the same way a real
T&A kiosk works. Credential enrollment and geofence configuration *are*
gated (`labour.configure`, Tenant Admin) since those are administrative
actions, not physical-presence ones.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import datetime, timedelta, timezone

from app.core.attendance import (
    check_geofence,
    clock_in,
    clock_out,
    has_open_session,
    hash_pin,
    list_site_attendance,
    to_aware,
)
from app.core.kiosk import KioskContext, verify_worker
from app.dependencies import get_db, get_kiosk_context, get_request_context
from app.errors import AuthForbidden, RunNotFound, ScopeError
from app.models.attendance import SiteGeofence, WorkerCredential
from app.models.canonical import ShiftAssignment, Worker
from app.schemas.attendance import (
    ClockInRequest,
    ClockInResponse,
    ClockOutRequest,
    ClockOutResponse,
    CredentialEnrollRequest,
    CredentialEnrollResponse,
    SiteAttendanceEntry,
    SiteGeofenceRequest,
    UpcomingShift,
    WhoamiRequest,
    WhoamiResponse,
)
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["attendance"])


def _kiosk_site(kiosk: KioskContext, requested: str | None) -> str:
    """The site is the device's, never the caller's claim: default to its only site; otherwise
    the request must name one of the device's enrolled sites."""
    if requested is None:
        if len(kiosk.site_ids) == 1:
            return kiosk.site_ids[0]
        raise ScopeError("site_id required for a multi-site device")
    if requested not in kiosk.site_ids:
        raise ScopeError("requested site_id exceeds the device's enrolled sites")
    return requested


def _mask(worker_id: str) -> str:
    return "•" * max(len(worker_id) - 3, 2) + worker_id[-3:]


@router.post("/attendance/credentials", response_model=CredentialEnrollResponse, status_code=201)
def enroll_credential(
    request: CredentialEnrollRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> CredentialEnrollResponse:
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to enroll a clock-in credential")

    worker = db.get(Worker, request.worker_id)
    if worker is None or worker.tenant_id != context.tenant_id:
        raise RunNotFound(f"worker '{request.worker_id}' not found or not visible in caller scope")

    credential = db.get(WorkerCredential, request.worker_id)
    if credential is None:
        credential = WorkerCredential(worker_id=request.worker_id, tenant_id=context.tenant_id)
        db.add(credential)
    if request.pin:
        credential.pin_hash = hash_pin(request.pin)
    if request.nfc_tag_id:
        credential.nfc_tag_id = request.nfc_tag_id
    db.flush()

    return CredentialEnrollResponse(worker_id=worker.worker_id, has_pin=credential.pin_hash is not None, has_nfc=credential.nfc_tag_id is not None)


@router.post("/attendance/clock-in", response_model=ClockInResponse)
def clock_in_endpoint(
    request: ClockInRequest,
    kiosk: KioskContext = Depends(get_kiosk_context),
    db: Session = Depends(get_db),
) -> ClockInResponse:
    site_id = _kiosk_site(kiosk, request.site_id)
    worker = verify_worker(db, kiosk, method=request.method, worker_id=request.worker_id, pin=request.pin, nfc_tag_id=request.nfc_tag_id)

    geofence_status = "skipped"
    if request.gps:
        geofence_status = check_geofence(db, kiosk.tenant_id, site_id, request.gps.latitude, request.gps.longitude)

    result = clock_in(db, kiosk.tenant_id, site_id, worker, geofence_status)
    return ClockInResponse(
        worker_id=worker.worker_id,
        attendance_session_id=result.session.id,
        clocked_in_at=result.session.start_at,
        geofence_status=result.geofence_status,  # type: ignore[arg-type]
        matched_rostered_shift=result.matched_rostered_shift,
    )


@router.post("/attendance/clock-out", response_model=ClockOutResponse)
def clock_out_endpoint(
    request: ClockOutRequest,
    kiosk: KioskContext = Depends(get_kiosk_context),
    db: Session = Depends(get_db),
) -> ClockOutResponse:
    worker = verify_worker(db, kiosk, method=request.method, worker_id=request.worker_id, pin=request.pin, nfc_tag_id=request.nfc_tag_id)
    session = clock_out(db, kiosk.tenant_id, worker)
    duration_minutes = (to_aware(session.end_at) - to_aware(session.start_at)).total_seconds() / 60
    return ClockOutResponse(
        worker_id=worker.worker_id,
        attendance_session_id=session.id,
        clocked_in_at=session.start_at,
        clocked_out_at=session.end_at,
        duration_minutes=round(duration_minutes, 2),
    )


@router.post("/site-geofences", status_code=201)
def create_site_geofence(
    request: SiteGeofenceRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to configure a site geofence")

    geofence = db.get(SiteGeofence, (context.tenant_id, request.site_id))
    if geofence is None:
        geofence = SiteGeofence(tenant_id=context.tenant_id, site_id=request.site_id, latitude=request.latitude, longitude=request.longitude, radius_meters=request.radius_meters)
        db.add(geofence)
    else:
        geofence.latitude = request.latitude
        geofence.longitude = request.longitude
        geofence.radius_meters = request.radius_meters
    db.flush()
    return {"tenant_id": context.tenant_id, "site_id": request.site_id, "latitude": request.latitude, "longitude": request.longitude, "radius_meters": request.radius_meters}


@router.get("/workers/{worker_id}/shifts", response_model=list[UpcomingShift])
def get_worker_shifts(
    worker_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> list[UpcomingShift]:
    """Supervisor/planner view of a worker's shifts: requires labour.read and the worker's home
    site inside the caller's finite site grants (foreign ids give a non-enumerating 404). A worker
    seeing their own shifts uses the kiosk `whoami` after credential verification.
    """
    if not context.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read")
    worker = db.get(Worker, worker_id)
    if worker is None or worker.tenant_id != context.tenant_id or worker.home_site not in context.site_ids:
        raise RunNotFound(f"worker '{worker_id}' not found or not visible in caller scope")

    rows = db.scalars(
        select(ShiftAssignment)
        .where(ShiftAssignment.tenant_id == context.tenant_id)
        .where(ShiftAssignment.worker_id == worker_id)
        .order_by(ShiftAssignment.start_at.asc())
    ).all()
    return [
        UpcomingShift(shift_id=r.shift_id, role=r.role, zone=r.zone, start_at=r.start_at, end_at=r.end_at, status=r.status)
        for r in rows
    ]


@router.post("/attendance/whoami", response_model=WhoamiResponse)
def whoami(
    request: WhoamiRequest,
    kiosk: KioskContext = Depends(get_kiosk_context),
    db: Session = Depends(get_db),
) -> WhoamiResponse:
    """Resolves a worker from their PIN/NFC without clocking in — the
    console's Kiosk page uses this to greet the worker and show their
    shifts before they choose to clock in/out (a genuine clock-in commits
    an AttendanceSession row; this is read-only).
    """
    worker = verify_worker(db, kiosk, method=request.method, worker_id=request.worker_id, pin=request.pin, nfc_tag_id=request.nfc_tag_id)
    now = datetime.now(timezone.utc)
    rows = db.scalars(
        select(ShiftAssignment)
        .where(ShiftAssignment.tenant_id == kiosk.tenant_id, ShiftAssignment.worker_id == worker.worker_id, ShiftAssignment.end_at >= now)
        .order_by(ShiftAssignment.start_at.asc()).limit(10)
    ).all()
    return WhoamiResponse(
        worker_id=worker.worker_id,
        masked_identity=_mask(worker.worker_id),
        employment_type=worker.employment_type,
        home_site=worker.home_site,
        has_open_session=has_open_session(db, kiosk.tenant_id, worker.worker_id),
        upcoming_shifts=[UpcomingShift(shift_id=r.shift_id, role=r.role, zone=r.zone, start_at=r.start_at, end_at=r.end_at, status=r.status) for r in rows],
    )


@router.get("/sites/{site_id}/attendance", response_model=list[SiteAttendanceEntry])
def get_site_attendance(
    site_id: str,
    since_hours: int = 24,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> list[SiteAttendanceEntry]:
    """Supervisor's "who's here, and is anyone off-roster" view (Business
    Spec §8: "cover shifts, manage exceptions, respond to live alerts").
    `matched_rostered_shift: false` is the exception signal — a starting
    point, not a full exception/alerting system (see
    app/core/attendance.py's docstring).
    """
    # No `context.site_ids and ...` guard -- see runs.py's _enforce_scope
    # for why (docs/tenant-isolation-inventory.md).
    if not context.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read")
    if site_id not in context.site_ids:
        raise ScopeError("requested site_id exceeds the caller's authorised scope")

    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
    summaries = list_site_attendance(db, context.tenant_id, site_id, since)
    return [
        SiteAttendanceEntry(
            worker_id=s.session.worker_id,
            attendance_session_id=s.session.id,
            clocked_in_at=s.session.start_at,
            clocked_out_at=s.session.end_at,
            matched_rostered_shift=s.matched_rostered_shift,
        )
        for s in summaries
    ]
