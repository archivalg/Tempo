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

from app.core import timeclock
from app.core.attendance import (
    check_geofence,
    has_open_session,
    hash_pin,
    list_site_attendance,
    to_aware,
)
from app.core import auth
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
    PunchRequest,
    PunchResponse,
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
        credential.failed_attempts, credential.locked_until = 0, None  # a reset by authorised staff also clears a lockout
        auth.audit(db, actor_type="user", actor_id=context.user_id, tenant_id=context.tenant_id, action="credential.pin_set", decision="allowed", session_ref=worker.worker_id,
                   correlation_id=context.correlation_id)
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
    worker = verify_worker(db, kiosk, method=request.method, worker_id=request.worker_id, worker_no=request.worker_no, pin=request.pin, nfc_tag_id=request.nfc_tag_id, qr_token=request.qr_token)

    geofence_status = "skipped"
    mode = timeclock.get_policy(db, kiosk.tenant_id, site_id).location_mode
    if request.gps and mode == "off" and request.gps.latitude is not None and request.gps.longitude is not None:
        geofence_status = check_geofence(db, kiosk.tenant_id, site_id, request.gps.latitude, request.gps.longitude)  # earlier behaviour: a supplied position is enforced

    result = timeclock.punch(db, kiosk.tenant_id, site_id, kiosk.device_id, worker, "clock_in", fix=_fix(request.gps))
    if mode != "off":
        geofence_status = "passed" if result.punch.location_status == "passed" else "skipped"
    return ClockInResponse(
        worker_id=worker.worker_id,
        attendance_session_id=result.session.id,
        clocked_in_at=result.punch.at,
        geofence_status=geofence_status,  # type: ignore[arg-type]
        matched_rostered_shift=result.session.rostered_shift_id is not None,
        state=result.session.state,
        duplicate=result.duplicate,
    )


def _fix(g) -> timeclock.Fix | None:
    return None if g is None else timeclock.Fix(g.latitude, g.longitude, g.accuracy_m, g.error)


def _punch_site(db: Session, kiosk: KioskContext, worker: Worker) -> str:
    """Break and clock-out belong to the site of the session being closed (a multi-site device never guesses)."""
    s = timeclock.open_session(db, kiosk.tenant_id, worker.worker_id)
    return s.site_id if s and s.site_id in kiosk.site_ids else (worker.home_site if worker.home_site in kiosk.site_ids else kiosk.site_ids[0])


@router.post("/attendance/clock-out", response_model=ClockOutResponse)
def clock_out_endpoint(
    request: ClockOutRequest,
    kiosk: KioskContext = Depends(get_kiosk_context),
    db: Session = Depends(get_db),
) -> ClockOutResponse:
    worker = verify_worker(db, kiosk, method=request.method, worker_id=request.worker_id, worker_no=request.worker_no, pin=request.pin, nfc_tag_id=request.nfc_tag_id, qr_token=request.qr_token)
    result = timeclock.punch(db, kiosk.tenant_id, _punch_site(db, kiosk, worker), kiosk.device_id, worker, "clock_out", fix=_fix(request.gps))
    s = result.session
    duration_minutes = (to_aware(s.end_at) - to_aware(s.start_at)).total_seconds() / 60
    return ClockOutResponse(
        worker_id=worker.worker_id,
        attendance_session_id=s.id,
        clocked_in_at=s.start_at,
        clocked_out_at=s.end_at,
        duration_minutes=round(duration_minutes, 2),
        state=s.state,
        duplicate=result.duplicate,
        break_minutes=s.breaks_minutes or 0,
    )


def _break(action: str):
    def handler(request: PunchRequest, kiosk: KioskContext = Depends(get_kiosk_context), db: Session = Depends(get_db)) -> PunchResponse:
        worker = verify_worker(db, kiosk, method=request.method, worker_id=request.worker_id, worker_no=request.worker_no, pin=request.pin, nfc_tag_id=request.nfc_tag_id, qr_token=request.qr_token)
        r = timeclock.punch(db, kiosk.tenant_id, _punch_site(db, kiosk, worker), kiosk.device_id, worker, action, fix=_fix(request.gps))
        return PunchResponse(worker_id=worker.worker_id, attendance_session_id=r.session.id, action=action, state=r.session.state, recorded_at=r.punch.at,
                             duplicate=r.duplicate, break_minutes=r.session.breaks_minutes or 0)
    return handler


router.post("/attendance/break-start", response_model=PunchResponse)(_break("break_start"))
router.post("/attendance/break-end", response_model=PunchResponse)(_break("break_end"))


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
    worker = verify_worker(db, kiosk, method=request.method, worker_id=request.worker_id, worker_no=request.worker_no, pin=request.pin, nfc_tag_id=request.nfc_tag_id, qr_token=request.qr_token, consume_qr=False)
    now = datetime.now(timezone.utc)
    open_s = timeclock.open_session(db, kiosk.tenant_id, worker.worker_id)
    state = open_s.state if open_s else "not_clocked_in"
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
        has_open_session=open_s is not None,
        state=state,
        location_mode=timeclock.get_policy(db, kiosk.tenant_id, worker.home_site if worker.home_site in kiosk.site_ids else kiosk.site_ids[0]).location_mode,
        allowed_actions={"not_clocked_in": ["clock_in"], "working": ["break_start", "clock_out"], "on_break": ["break_end", "clock_out"]}[state],
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
