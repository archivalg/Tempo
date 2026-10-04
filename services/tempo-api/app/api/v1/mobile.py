"""Employee mobile API. Everything here is about the signed-in employee's OWN worker record, resolved on the server from the account link,
never from an identifier the app sends. An employee account carries only `labour.self`, so it cannot reach any manager endpoint."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth, employee_data as ed, kiosk_qr, offers as offers_core, password_login as pl, push, timeclock
from app.core.notifications import recipients as manager_recipients
from app.db import begin_auth_lookup
from app.dependencies import get_db, get_principal, get_request_context
from app.errors import AuthForbidden, AuthInvalid, PolicyConflict, RunNotFound, ScopeError
from app.models.attendance import AttendancePunch
from app.models.canonical import Availability, AttendanceSession, ShiftAssignment, Worker
from app.models.directory import Site
from app.models.identity import Tenant, TempoUser
from app.models.mobile import (LeaveRequest, NotificationPreference, PushDelivery, PushDevice, ShiftChangeEvent, ShiftOffer, ShiftOfferRecipient, WorkerUserLink)
from app.models.rosters import Notification
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["mobile"])


# ------------------------------------------------------------------------------------------------------------------ authentication
class MobileLogin(BaseModel):
    username: str
    password: str


class MobileMfa(BaseModel):
    challenge: str
    code: str


class MobileMfaResend(BaseModel):
    challenge: str


class MobileRefresh(BaseModel):
    refresh_token: str


def _tokens(issued: auth.IssuedSession) -> dict:
    return {"status": "signed_in", "access_token": issued.access_token, "refresh_token": issued.refresh_token, "expires_at": issued.access_expires_at.isoformat(),
            "refresh_expires_at": issued.refresh_expires_at.isoformat()}


def _cid(request: Request) -> str:
    return getattr(request.state, "correlation_id", "n/a")


@router.post("/mobile/auth/login")
def mobile_login(body: MobileLogin, request: Request, db: Session = Depends(get_db)) -> dict:
    """Same checks as the web sign-in (throttle, lockout, MFA when required). The tokens come back in the body for the app's secure storage; no cookies."""
    out = pl.password_login(db, request, body.username, body.password, _cid(request))
    if out.kind == "mfa_required":
        return {"status": "mfa_required", "challenge": out.challenge, "method": out.method, "sent": out.sent, "hint": out.hint}
    return {**_tokens(out.issued), "mfa_enrol_required": out.kind == "mfa_enrol_required"}


@router.post("/mobile/auth/mfa/resend")
def mobile_mfa_resend(body: MobileMfaResend, request: Request, db: Session = Depends(get_db)) -> dict:
    return pl.mfa_resend(db, request, body.challenge, _cid(request))


@router.post("/mobile/auth/mfa")
def mobile_mfa(body: MobileMfa, request: Request, db: Session = Depends(get_db)) -> dict:
    return _tokens(pl.mfa_verify(db, request, body.challenge, body.code, _cid(request)))


@router.post("/mobile/auth/refresh")
def mobile_refresh(body: MobileRefresh, request: Request, db: Session = Depends(get_db)) -> dict:
    """Rotates the refresh token. A reused or revoked one fails and the app must sign in again."""
    return _tokens(auth.rotate_refresh(db, body.refresh_token, correlation_id=_cid(request)))


# ------------------------------------------------------------------------------------------------------------------ the employee principal
@dataclass
class Employee:
    ctx: RequestContext
    worker: Worker
    site: Site


def get_employee(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> Employee:
    if not ctx.has_permission("labour.self"):
        raise AuthForbidden("this part of Tempo is for employees")
    link = db.scalar(select(WorkerUserLink).where(WorkerUserLink.tenant_id == ctx.tenant_id, WorkerUserLink.user_id == ctx.user_id))
    w = db.get(Worker, link.worker_id) if link else None
    if w is None or w.tenant_id != ctx.tenant_id or w.status != "active" or w.home_site not in ctx.site_ids:
        raise AuthForbidden("your account is not linked to an active employee record. Ask your manager.")
    site = db.get(Site, (ctx.tenant_id, w.home_site))
    if site is None:
        raise AuthForbidden("your site is not available")
    return Employee(ctx, w, site)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/mobile/auth/logout")
def mobile_logout(body: dict | None = None, principal: auth.ResolvedPrincipal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    from app.models.identity import UserSession
    begin_auth_lookup(db)
    row = db.get(UserSession, principal.session_id)
    if row is not None:
        auth.revoke_family(db, row.session_family_id, reason="logout")
    return {"status": "signed_out"}


@router.get("/me/profile")
def profile(e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    t = db.get(Tenant, e.ctx.tenant_id)
    from app.models.directory import WorkerPerson
    p = db.get(WorkerPerson, e.worker.worker_id)
    return {"user_id": e.ctx.user_id, "worker_id": e.worker.worker_id, "display_name": p.display_name if p else None, "company": t.name if t else e.ctx.tenant_id, "tenant_id": e.ctx.tenant_id,
            "site": {"site_id": e.site.site_id, "name": e.site.name, "timezone": e.site.timezone}, "employment_type": e.worker.employment_type, "server_time": _now().isoformat()}


# ------------------------------------------------------------------------------------------------------------------ shifts and changes
@router.get("/me/shifts")
def my_shifts(start: date | None = None, end: date | None = None, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    """Published shifts only. Drafts, submitted and approved-but-unpublished rosters are never returned."""
    tz = ZoneInfo(e.site.timezone)
    today = _now().astimezone(tz).date()
    s, f = start or today - timedelta(days=1), end or today + timedelta(days=30)
    if f < s or (f - s).days > 92:
        raise ScopeError("choose a range of at most 92 days")
    lo = datetime(s.year, s.month, s.day, tzinfo=tz).astimezone(timezone.utc)
    hi = datetime(f.year, f.month, f.day, tzinfo=tz).astimezone(timezone.utc) + timedelta(days=1)
    re = ed.reconfirm_ids(db, e.ctx.tenant_id, e.worker.worker_id)
    return {"as_of": _now().isoformat(), "timezone": e.site.timezone,
            "shifts": [ed.shift_view(x, e.site, reconfirm=bool(x.source_ref and x.source_ref.startswith("offer:") and x.source_ref[6:] in re)) for x in ed.visible_shifts(db, e.ctx.tenant_id, e.worker.worker_id, lo, hi)]}


@router.get("/me/shifts/{shift_id}")
def my_shift(shift_id: str, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    sh = db.get(ShiftAssignment, shift_id)
    if sh is None or sh.tenant_id != e.ctx.tenant_id or sh.worker_id != e.worker.worker_id or sh.status != "committed":
        raise RunNotFound("shift not found")
    re = ed.reconfirm_ids(db, e.ctx.tenant_id, e.worker.worker_id)
    return ed.shift_view(sh, e.site, reconfirm=bool(sh.source_ref and sh.source_ref.startswith("offer:") and sh.source_ref[6:] in re))


@router.get("/me/changes")
def my_changes(days: int = Query(default=30, ge=1, le=90), e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(ShiftChangeEvent).where(ShiftChangeEvent.tenant_id == e.ctx.tenant_id, ShiftChangeEvent.worker_id == e.worker.worker_id, ShiftChangeEvent.at >= _now() - timedelta(days=days))
                      .order_by(ShiftChangeEvent.at.desc()).limit(200)).all()
    return {"unseen": sum(1 for r in rows if r.seen_at is None), "changes": [{"id": r.id, "kind": r.kind, "shift_id": r.shift_id, "before": r.before, "after": r.after, "at": r.at.isoformat(), "seen": r.seen_at is not None} for r in rows]}


@router.post("/me/changes/seen")
def changes_seen(e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    n = 0
    for r in db.scalars(select(ShiftChangeEvent).where(ShiftChangeEvent.tenant_id == e.ctx.tenant_id, ShiftChangeEvent.worker_id == e.worker.worker_id, ShiftChangeEvent.seen_at.is_(None))):
        r.seen_at = _now()
        n += 1
    return {"marked": n}


# ------------------------------------------------------------------------------------------------------------------ offers
class OfferResponse(BaseModel):
    action: str = Field(pattern="^(accept|decline)$")
    note: str | None = Field(default=None, max_length=300)


@router.get("/me/offers")
def my_offers(e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    ids = [r.offer_id for r in db.scalars(select(ShiftOfferRecipient).where(ShiftOfferRecipient.tenant_id == e.ctx.tenant_id, ShiftOfferRecipient.worker_id == e.worker.worker_id))]
    out = []
    now = _now()
    for o in db.scalars(select(ShiftOffer).where(ShiftOffer.tenant_id == e.ctx.tenant_id, ShiftOffer.id.in_(ids or [""])).order_by(ShiftOffer.start_at.desc()).limit(100)):
        offers_core._expire_if_due(o, now)
        out.append(offers_core.offer_view(db, o, worker_id=e.worker.worker_id))
    return {"offers": out}


@router.post("/me/offers/{offer_id}/respond")
def respond_offer(offer_id: str, body: OfferResponse, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    o = offers_core.respond(db, e.ctx.tenant_id, offer_id, e.worker, body.action, body.note)
    auth.audit(db, actor_type="user", actor_id=e.ctx.user_id, tenant_id=e.ctx.tenant_id, action=f"offer.{body.action}", decision="allowed", session_ref=offer_id, correlation_id=e.ctx.correlation_id)
    return offers_core.offer_view(db, o, worker_id=e.worker.worker_id)


# ------------------------------------------------------------------------------------------------------------------ availability
class AvailabilityIn(BaseModel):
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def _tz(cls, d: datetime) -> datetime:
        if d.tzinfo is None:
            raise ValueError("timestamps must carry a timezone offset")
        return d.astimezone(timezone.utc)


def _avail_view(a: Availability) -> dict:
    return {"id": a.id, "start_at": ed.aware(a.interval_start).isoformat(), "end_at": ed.aware(a.interval_end).isoformat(), "status": a.status, "source": a.source_system, "editable": a.source_system == "tempo_employee"}


@router.get("/me/availability")
def my_availability(e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(Availability).where(Availability.tenant_id == e.ctx.tenant_id, Availability.worker_id == e.worker.worker_id, Availability.interval_end > _now(),
                                                 Availability.status.in_(("unavailable", "leave", "rdo"))).order_by(Availability.interval_start)).all()
    return {"entries": [_avail_view(a) for a in rows]}


@router.post("/me/availability", status_code=201)
def add_my_availability(body: AvailabilityIn, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    """Times you cannot work. They take effect straight away as a scheduling conflict for managers and are labelled as coming from you."""
    now = _now()
    if body.end_at <= body.start_at or body.end_at - body.start_at > timedelta(days=14):
        raise ScopeError("choose a period that ends after it starts and lasts at most 14 days")
    if body.end_at <= now or body.start_at > now + timedelta(days=180):
        raise ScopeError("choose a period in the next 6 months")
    mine = db.scalars(select(Availability).where(Availability.tenant_id == e.ctx.tenant_id, Availability.worker_id == e.worker.worker_id, Availability.source_system == "tempo_employee", Availability.interval_end > now)).all()
    if len(mine) >= 50:
        raise PolicyConflict("you already have 50 upcoming entries; remove some first")
    if any(ed.aware(a.interval_start) < body.end_at and ed.aware(a.interval_end) > body.start_at for a in mine):
        raise PolicyConflict("you already have an entry overlapping that period")
    a = Availability(tenant_id=e.ctx.tenant_id, worker_id=e.worker.worker_id, interval_start=body.start_at, interval_end=body.end_at, status="unavailable", source_system="tempo_employee")
    db.add(a)
    db.flush()
    auth.audit(db, actor_type="user", actor_id=e.ctx.user_id, tenant_id=e.ctx.tenant_id, action="availability.submit", decision="allowed", session_ref=a.id, correlation_id=e.ctx.correlation_id)
    push.notify_user(db, e.ctx.tenant_id, manager_recipients(db, e.ctx.tenant_id, e.site.site_id, "labour.plan"), category="decisions", kind="availability.submitted", title="Availability submitted",
                     body="An employee marked time as unavailable.", dedup_key=f"availability:{a.id}", deep_link="/roster", site_id=e.site.site_id, link="/roster")
    return _avail_view(a)


@router.delete("/me/availability/{entry_id}")
def remove_my_availability(entry_id: str, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    a = db.get(Availability, entry_id)
    if a is None or a.tenant_id != e.ctx.tenant_id or a.worker_id != e.worker.worker_id:
        raise RunNotFound("entry not found")
    if a.source_system != "tempo_employee":
        raise PolicyConflict("this entry did not come from you; ask your manager to change it")
    if ed.aware(a.interval_start) <= _now():
        raise PolicyConflict("this period has already started")
    db.delete(a)
    auth.audit(db, actor_type="user", actor_id=e.ctx.user_id, tenant_id=e.ctx.tenant_id, action="availability.remove", decision="allowed", session_ref=entry_id, correlation_id=e.ctx.correlation_id)
    return {"removed": True}


# ------------------------------------------------------------------------------------------------------------------ leave
class LeaveIn(BaseModel):
    kind: str = Field(pattern="^(annual|personal|unpaid|other)$")
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=300)


def leave_view(r: LeaveRequest) -> dict:
    return {"id": r.id, "worker_id": r.worker_id, "kind": r.kind, "start_date": r.start_date.isoformat(), "end_date": r.end_date.isoformat(), "reason": r.reason, "status": r.status,
            "created_at": r.created_at.isoformat(), "decided_at": r.decided_at.isoformat() if r.decided_at else None, "decision_note": r.decision_note}


@router.get("/me/leave")
def my_leave(e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(LeaveRequest).where(LeaveRequest.tenant_id == e.ctx.tenant_id, LeaveRequest.worker_id == e.worker.worker_id).order_by(LeaveRequest.start_date.desc()).limit(100)).all()
    return {"requests": [leave_view(r) for r in rows]}


@router.post("/me/leave", status_code=201)
def request_leave(body: LeaveIn, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    tz = ZoneInfo(e.site.timezone)
    today = _now().astimezone(tz).date()
    if body.end_date < body.start_date or (body.end_date - body.start_date).days > 60:
        raise ScopeError("choose dates where the end is not before the start, covering at most 61 days")
    if body.start_date < today:
        raise ScopeError("leave must start today or later; ask your manager to record past leave")
    clash = db.scalar(select(LeaveRequest.id).where(LeaveRequest.tenant_id == e.ctx.tenant_id, LeaveRequest.worker_id == e.worker.worker_id, LeaveRequest.status.in_(("pending", "approved")),
                                                    LeaveRequest.start_date <= body.end_date, LeaveRequest.end_date >= body.start_date).limit(1))
    if clash:
        raise PolicyConflict("you already have a leave request covering some of those days")
    r = LeaveRequest(tenant_id=e.ctx.tenant_id, site_id=e.site.site_id, worker_id=e.worker.worker_id, kind=body.kind, start_date=body.start_date, end_date=body.end_date, reason=body.reason)
    db.add(r)
    db.flush()
    auth.audit(db, actor_type="user", actor_id=e.ctx.user_id, tenant_id=e.ctx.tenant_id, action="leave.request", decision="allowed", session_ref=r.id, correlation_id=e.ctx.correlation_id)
    push.notify_user(db, e.ctx.tenant_id, manager_recipients(db, e.ctx.tenant_id, e.site.site_id, "labour.approve"), category="decisions", kind="leave.requested", title="Leave request awaiting a decision",
                     body=f"{body.kind} leave {body.start_date} to {body.end_date}.", dedup_key=f"leave:{r.id}:requested", deep_link="/requests", site_id=e.site.site_id, link="/requests")
    return leave_view(r)


@router.delete("/me/leave/{leave_id}")
def cancel_leave(leave_id: str, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    from app.api.v1.mobile_manage import cancel_leave_core
    r = db.get(LeaveRequest, leave_id)
    if r is None or r.tenant_id != e.ctx.tenant_id or r.worker_id != e.worker.worker_id:
        raise RunNotFound("request not found")
    cancel_leave_core(db, r, e.site, e.ctx.user_id)
    return leave_view(r)


# ------------------------------------------------------------------------------------------------------------------ attendance history
@router.get("/me/attendance")
def my_attendance(days: int = Query(default=30, ge=1, le=92), e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    now = _now()
    tz = ZoneInfo(e.site.timezone)
    pol = timeclock.get_policy(db, e.ctx.tenant_id, e.site.site_id)
    sessions = db.scalars(select(AttendanceSession).where(AttendanceSession.tenant_id == e.ctx.tenant_id, AttendanceSession.worker_id == e.worker.worker_id, AttendanceSession.start_at >= now - timedelta(days=days))
                          .order_by(AttendanceSession.start_at.desc()).limit(200)).all()
    from app.models.rosters import AttendanceAdjustment
    adjs = {a.session_id: a for a in db.scalars(select(AttendanceAdjustment).where(AttendanceAdjustment.tenant_id == e.ctx.tenant_id, AttendanceAdjustment.session_id.in_([s.id for s in sessions] or [""]), AttendanceAdjustment.state == "approved"))}
    punches: dict[str, list] = {}
    for p in db.scalars(select(AttendancePunch).where(AttendancePunch.tenant_id == e.ctx.tenant_id, AttendancePunch.session_id.in_([s.id for s in sessions] or [""])).order_by(AttendancePunch.at)):
        punches.setdefault(p.session_id, []).append({"kind": p.kind, "at": ed.aware(p.at).isoformat(), "at_local": ed.aware(p.at).astimezone(tz).isoformat(), "source": p.source})
    out = []
    for s in sessions:
        h = timeclock.hours(s, adjs.get(s.id), pol, now)
        out.append({"id": s.id, "state": s.state, "started_at": ed.aware(s.start_at).isoformat(), "started_local": ed.aware(s.start_at).astimezone(tz).isoformat(), "ended_at": ed.aware(s.end_at).isoformat() if s.end_at else None,
                    "approval": s.approval, "corrected": s.id in adjs, "worked_minutes": h["worked_minutes"], "break_minutes": h["break_minutes"],
                    "payable_minutes": h["payable_minutes"] if s.approval == "approved" else None, "punches": punches.get(s.id, [])})
    open_s = timeclock.open_session(db, e.ctx.tenant_id, e.worker.worker_id)
    return {"timezone": e.site.timezone, "current_state": open_s.state if open_s else "not_clocked_in", "sessions": out,
            "note": "Payable hours appear once your manager approves the timesheet. Clocking is done at your site's kiosk."}


# ------------------------------------------------------------------------------------------------------------------ notification settings, devices, inbox
class PrefsIn(BaseModel):
    push_enabled: bool
    roster_published: bool
    shift_changes: bool
    offers: bool
    reminders: bool
    decisions: bool
    reminder_lead_minutes: int
    sms_opt_in: bool = False
    sms_number: str | None = Field(default=None, pattern=r"^\+[1-9][0-9]{7,14}$")

    @field_validator("reminder_lead_minutes")
    @classmethod
    def _lead(cls, v: int) -> int:
        if v not in push.LEAD_CHOICES:
            raise ValueError(f"reminder lead must be one of {', '.join(map(str, push.LEAD_CHOICES))} minutes")
        return v


def _prefs_out(db: Session, e: Employee) -> dict:
    p = push.prefs(db, e.ctx.tenant_id, e.ctx.user_id)
    from app.models.mobile import TenantMessaging
    tm = db.get(TenantMessaging, e.ctx.tenant_id)
    return {"push_enabled": p.push_enabled, "roster_published": p.roster_published, "shift_changes": p.shift_changes, "offers": p.offers, "reminders": p.reminders, "decisions": p.decisions,
            "reminder_lead_minutes": p.reminder_lead_minutes, "lead_choices": list(push.LEAD_CHOICES), "sms_opt_in": p.sms_opt_in, "sms_number": p.sms_number,
            "sms_available": bool(tm and tm.sms_enabled), "company_push_enabled": tm.push_enabled if tm else True}


@router.get("/me/notification-preferences")
def get_prefs(e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    return _prefs_out(db, e)


@router.put("/me/notification-preferences")
def put_prefs(body: PrefsIn, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    if body.sms_opt_in and not body.sms_number:
        raise ScopeError("add a mobile number in international format (for example +61400000000) to receive text messages")
    row = db.get(NotificationPreference, (e.ctx.tenant_id, e.ctx.user_id))
    if row is None:
        row = NotificationPreference(tenant_id=e.ctx.tenant_id, user_id=e.ctx.user_id)
        db.add(row)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    row.updated_at = _now()
    db.flush()
    auth.audit(db, actor_type="user", actor_id=e.ctx.user_id, tenant_id=e.ctx.tenant_id, action="notification.prefs_set", decision="allowed", reason_code=f"lead={body.reminder_lead_minutes}", correlation_id=e.ctx.correlation_id)
    return _prefs_out(db, e)


class DeviceIn(BaseModel):
    token: str = Field(min_length=10, max_length=300)
    platform: str = Field(pattern="^(ios|android)$")
    provider: str = Field(default="expo", pattern="^expo$")
    app_version: str | None = Field(default=None, max_length=40)
    label: str | None = Field(default=None, max_length=80)


@router.post("/me/push-devices", status_code=201)
def register_device(body: DeviceIn, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    """Idempotent: the same token again just refreshes it. A token that was registered to another person (a handed-over phone) moves to this one."""
    now = _now()
    d = db.scalar(select(PushDevice).where(PushDevice.tenant_id == e.ctx.tenant_id, PushDevice.token == body.token))
    if d is None:
        d = PushDevice(tenant_id=e.ctx.tenant_id, user_id=e.ctx.user_id, platform=body.platform, provider=body.provider, token=body.token, app_version=body.app_version, label=body.label)
        db.add(d)
    else:
        d.user_id, d.platform, d.app_version, d.label, d.revoked_at, d.invalid_at, d.invalid_reason = e.ctx.user_id, body.platform, body.app_version, body.label, None, None, None
    d.last_seen_at = now
    db.flush()
    return {"id": d.id, "registered": True}


@router.delete("/me/push-devices/{device_id}")
def remove_device(device_id: str, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    d = db.get(PushDevice, device_id)
    if d is None or d.tenant_id != e.ctx.tenant_id or d.user_id != e.ctx.user_id:
        raise RunNotFound("device not found")
    d.revoked_at, d.token = _now(), f"removed:{d.id}"   # the token itself is not kept
    return {"removed": True}


@router.get("/me/notifications")
def my_notifications(e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    rows = db.scalars(select(Notification).where(Notification.tenant_id == e.ctx.tenant_id, Notification.user_id == e.ctx.user_id).order_by(Notification.created_at.desc()).limit(50)).all()
    return {"unread": sum(1 for r in rows if r.read_at is None), "items": [{"id": r.id, "kind": r.kind, "title": r.title, "body": r.body, "deep_link": r.link, "created_at": r.created_at.isoformat(), "read": r.read_at is not None} for r in rows]}


@router.post("/me/notifications/{notification_id}/read")
def read_notification(notification_id: str, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    n = db.get(Notification, notification_id)
    if n is None or n.tenant_id != e.ctx.tenant_id or n.user_id != e.ctx.user_id:
        raise RunNotFound("notification not found")
    n.read_at = n.read_at or _now()
    return {"read": True}


class Ack(BaseModel):
    device_id: str | None = None


@router.post("/me/notifications/{notification_id}/ack")
def ack_notification(notification_id: str, body: Ack, e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    """The app reports it received or opened a notification. This, and only this, marks a delivery acknowledged by the employee's device."""
    n = db.get(Notification, notification_id)
    if n is None or n.tenant_id != e.ctx.tenant_id or n.user_id != e.ctx.user_id:
        raise RunNotFound("notification not found")
    mine = {d.id for d in db.scalars(select(PushDevice).where(PushDevice.tenant_id == e.ctx.tenant_id, PushDevice.user_id == e.ctx.user_id))}
    k = 0
    for d in db.scalars(select(PushDelivery).where(PushDelivery.tenant_id == e.ctx.tenant_id, PushDelivery.notification_id == notification_id, PushDelivery.device_id.in_(mine or [""]))):
        if body.device_id is None or d.device_id == body.device_id:
            d.acknowledged_at = d.acknowledged_at or _now()
            k += 1
    return {"acknowledged": k}


# ------------------------------------------------------------------------------------------------------------------ kiosk identification
@router.post("/me/kiosk-qr")
def kiosk_qr_token(e: Employee = Depends(get_employee), db: Session = Depends(get_db)) -> dict:
    """A short-lived, single-use code for the employee's phone to show at a kiosk. It is never your PIN and expires within about a minute."""
    return kiosk_qr.issue(db, e.ctx.tenant_id, e.worker.worker_id)
