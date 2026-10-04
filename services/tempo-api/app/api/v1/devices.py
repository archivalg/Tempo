"""Kiosk device lifecycle. Admin routes need labour.configure and can only bind a device to
sites inside the admin's own finite grants (no delegation beyond own authority)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth, kiosk
from app.dependencies import get_db, get_kiosk_context, get_request_context
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
    client_info: dict | None = None    # platform and app version the device reported when it enrolled


def _out(d: KioskDevice, code: str | None = None) -> DeviceOut:
    return DeviceOut(device_id=d.device_id, name=d.name, site_ids=list(d.site_ids), status=d.status,
                     enrolled_at=d.enrolled_at, last_seen_at=d.last_seen_at, enrolment_code=code, client_info=d.client_info)


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
    platform: str | None = Field(default=None, pattern="^(ios|android|web)$")
    app_version: str | None = Field(default=None, max_length=40)


class EnrolResponse(BaseModel):
    device_id: str
    device_credential: str  # shown once; store in the device's secure storage
    site_ids: list[str]
    tenant_id: str


@router.post("/kiosk/enrol", response_model=EnrolResponse)
def enrol(body: EnrolRequest, request: Request, db: Session = Depends(get_db)) -> EnrolResponse:
    device, credential = kiosk.redeem_enrolment(db, body.enrolment_code, correlation_id=getattr(request.state, "correlation_id", "n/a"))
    device.client_info = {"platform": body.platform, "app_version": body.app_version}
    return EnrolResponse(device_id=device.device_id, device_credential=credential, site_ids=list(device.site_ids), tenant_id=device.tenant_id)


class ExitRequest(BaseModel):
    username: str
    password: str
    code: str | None = None          # authenticator code, for managers who use two-step verification
    challenge: str | None = None     # returned when a code is needed
    purpose: str = Field(default="exit", pattern="^(exit|reconfigure)$")
    revoke_device: bool = False


@router.post("/kiosk/exit-authorise")
def authorise_exit(body: ExitRequest, request: Request, kctx: kiosk.KioskContext = Depends(get_kiosk_context), db: Session = Depends(get_db)) -> dict:
    """A manager proves who they are on the kiosk to leave kiosk mode or reconfigure it. The tablet cannot do either on its own.
    The manager needs the configure permission for this device's tenant and sites; the attempt and its outcome are audited."""
    from app.core import password_login as pl
    from app.db import begin_auth_lookup, bind_sites, bind_tenant
    from app.models.identity import UserRoleAssignment, UserSiteGrant, TempoUser
    from app.core.permissions import permissions_for_roles
    cid = getattr(request.state, "correlation_id", "n/a")
    tenant_id, sites, device_id = kctx.tenant_id, list(kctx.site_ids), kctx.device_id
    try:
        if body.challenge:
            issued = pl.mfa_verify(db, request, body.challenge, body.code or "", cid)
        else:
            out = pl.password_login(db, request, body.username, body.password, cid)
            if out.kind == "mfa_required":
                return {"authorised": False, "mfa_required": True, "challenge": out.challenge, "method": out.method, "hint": out.hint}
            issued = out.issued
        uid = auth.verify_access_token(issued.access_token)["sub"]
        begin_auth_lookup(db)
        row = db.get(UserSession_model(), issued.session_id)
        if row is not None:
            auth.revoke_family(db, row.session_family_id, reason="kiosk_exit_check")   # a check only: no session is kept
        roles = list(db.scalars(select(UserRoleAssignment.role).where(UserRoleAssignment.user_id == uid, UserRoleAssignment.tenant_id == tenant_id)))
        granted = set(db.scalars(select(UserSiteGrant.site_id).where(UserSiteGrant.user_id == uid, UserSiteGrant.tenant_id == tenant_id)))
        ok = "labour.configure" in permissions_for_roles(roles) and set(sites) <= granted
        mfa_ok = (row is not None and row.mfa_verified_at is not None) or "tenant_admin" not in roles
    except Exception:
        db.flush()   # rows written during the sign-in check belong to the auth phase; write them before the tenant is bound again
        bind_tenant(db, tenant_id)
        bind_sites(db, sites)
        auth.audit(db, actor_type="kiosk", actor_id=device_id, tenant_id=tenant_id, action="kiosk.exit_authorise", decision="denied", reason_code="bad_credentials", correlation_id=cid)
        db.commit()
        raise
    db.flush()
    bind_tenant(db, tenant_id)
    bind_sites(db, sites)
    if not (ok and mfa_ok):
        auth.audit(db, actor_type="kiosk", actor_id=device_id, tenant_id=tenant_id, action="kiosk.exit_authorise", decision="denied", reason_code="not_a_manager_for_this_device" if not ok else "mfa_required", session_ref=uid, correlation_id=cid)
        db.commit()
        raise AuthForbidden("that person is not authorised to manage this kiosk")
    if body.revoke_device:
        d = db.get(KioskDevice, device_id)
        if d is not None:
            d.status, d.disabled_at = "disabled", datetime.now(timezone.utc)
    auth.audit(db, actor_type="user", actor_id=uid, tenant_id=tenant_id, action=f"kiosk.{body.purpose}_authorised", decision="allowed", reason_code="device_revoked" if body.revoke_device else None, session_ref=device_id, correlation_id=cid)
    return {"authorised": True, "purpose": body.purpose, "device_revoked": body.revoke_device}


def UserSession_model():
    from app.models.identity import UserSession
    return UserSession
