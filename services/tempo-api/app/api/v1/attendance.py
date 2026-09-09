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

from app.core.attendance import check_geofence, clock_in, clock_out, hash_pin, resolve_worker_by_nfc, resolve_worker_by_pin, to_aware
from app.dependencies import get_db, get_request_context
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
    SiteGeofenceRequest,
    UpcomingShift,
)
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["attendance"])


def _resolve_worker(db: Session, context: RequestContext, method: str, pin: str | None, nfc_tag_id: str | None) -> Worker:
    if method == "pin":
        return resolve_worker_by_pin(db, context.tenant_id, pin)  # type: ignore[arg-type]
    return resolve_worker_by_nfc(db, context.tenant_id, nfc_tag_id)  # type: ignore[arg-type]


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
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ClockInResponse:
    if context.site_ids and request.site_id not in context.site_ids:
        raise ScopeError("requested site_id exceeds the caller's authorised scope")

    worker = _resolve_worker(db, context, request.method, request.pin, request.nfc_tag_id)

    geofence_status = "skipped"
    if request.gps:
        geofence_status = check_geofence(db, context.tenant_id, request.site_id, request.gps.latitude, request.gps.longitude)

    result = clock_in(db, context.tenant_id, request.site_id, worker, geofence_status)
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
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ClockOutResponse:
    worker = _resolve_worker(db, context, request.method, request.pin, request.nfc_tag_id)
    session = clock_out(db, context.tenant_id, worker)
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
    """§8's Worker UX role: "Know shifts... get paid accurately." No
    per-worker identity exists yet (same Phase 0 stand-in as everything
    else — see app/dependencies.py), so this is scoped by tenant only: any
    caller in the tenant's scope can view any worker's shifts. A real
    deployment needs a worker to only ever see their own.
    """
    worker = db.get(Worker, worker_id)
    if worker is None or worker.tenant_id != context.tenant_id:
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
