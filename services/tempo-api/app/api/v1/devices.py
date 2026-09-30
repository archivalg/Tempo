"""Kiosk device lifecycle. Admin routes need labour.configure and can only bind a device to
sites inside the admin's own finite grants (no delegation beyond own authority)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth, kiosk
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, RunNotFound, ScopeError
from app.models.identity import KioskDevice
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["devices"])


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    site_ids: list[str] = Field(min_length=1, max_length=20)


class DeviceOut(BaseModel):
    device_id: str
    name: str | None
    site_ids: list[str]
    status: str
    enrolled_at: datetime | None
    last_seen_at: datetime | None
    enrolment_code: str | None = None  # returned once, at creation / re-issue only


def _out(d: KioskDevice, code: str | None = None) -> DeviceOut:
    return DeviceOut(device_id=d.device_id, name=d.name, site_ids=list(d.site_ids), status=d.status,
                     enrolled_at=d.enrolled_at, last_seen_at=d.last_seen_at, enrolment_code=code)


def _require(ctx: RequestContext) -> None:
    if not ctx.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure required to manage devices")


def _owned(db: Session, ctx: RequestContext, device_id: str) -> KioskDevice:
    d = db.get(KioskDevice, device_id)
    if d is None or d.tenant_id != ctx.tenant_id or not set(d.site_ids) <= set(ctx.site_ids):
        raise RunNotFound("device not found or not visible in caller scope")
    return d


@router.post("/devices", response_model=DeviceOut, status_code=201)
def create_device(body: DeviceCreate, request: Request, ctx: RequestContext = Depends(get_request_context),
                  db: Session = Depends(get_db)) -> DeviceOut:
    _require(ctx)
    if not set(body.site_ids) <= set(ctx.site_ids):
        raise ScopeError("device sites exceed the caller's authorised sites")
    d = KioskDevice(tenant_id=ctx.tenant_id, site_ids=sorted(set(body.site_ids)), name=body.name, created_by=ctx.user_id)
    db.add(d)
    db.flush()
    code = kiosk.new_enrolment_code(d)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="device.create",
               decision="allowed", session_ref=d.device_id, correlation_id=ctx.correlation_id)
    return _out(d, code)


@router.get("/devices", response_model=list[DeviceOut])
def list_devices(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[DeviceOut]:
    _require(ctx)
    rows = db.scalars(select(KioskDevice).where(KioskDevice.tenant_id == ctx.tenant_id)).all()
    return [_out(d) for d in rows if set(d.site_ids) <= set(ctx.site_ids)]


@router.post("/devices/{device_id}/enrolment-code", response_model=DeviceOut)
def reissue_code(device_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> DeviceOut:
    _require(ctx)
    d = _owned(db, ctx, device_id)
    if d.disabled_at is not None:
        raise ScopeError("device is disabled")
    code = kiosk.new_enrolment_code(d)  # invalidates the previous credential: re-enrolment
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="device.reenrol",
               decision="allowed", session_ref=d.device_id, correlation_id=ctx.correlation_id)
    return _out(d, code)


@router.post("/devices/{device_id}/disable", response_model=DeviceOut)
def disable_device(device_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> DeviceOut:
    _require(ctx)
    d = _owned(db, ctx, device_id)
    d.status, d.disabled_at, d.credential_reference = "disabled", datetime.now(timezone.utc), None
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="device.disable",
               decision="allowed", session_ref=d.device_id, correlation_id=ctx.correlation_id)
    return _out(d)


class EnrolRequest(BaseModel):
    enrolment_code: str = Field(min_length=8, max_length=200)


class EnrolResponse(BaseModel):
    device_id: str
    device_credential: str  # shown once; store in the device's secure storage
    site_ids: list[str]
    tenant_id: str


@router.post("/kiosk/enrol", response_model=EnrolResponse)
def enrol(body: EnrolRequest, request: Request, db: Session = Depends(get_db)) -> EnrolResponse:
    device, credential = kiosk.redeem_enrolment(db, body.enrolment_code, correlation_id=getattr(request.state, "correlation_id", "n/a"))
    return EnrolResponse(device_id=device.device_id, device_credential=credential, site_ids=list(device.site_ids), tenant_id=device.tenant_id)
