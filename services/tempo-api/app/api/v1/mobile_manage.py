"""Manager controls for the employee app: invite and unlink employees, shift offers, leave requests, messaging settings, delivery tracking."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.v1.operations import _site
from app.core import auth, offers as oc, password_login as pl, push
from app.core.notifications import recipients as manager_recipients
from app.core.opsview import local_day_bounds
from app.db import auth_phase
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, PolicyConflict, RunNotFound, ScopeError
from app.models.canonical import Availability, ShiftAssignment, Worker
from app.models.directory import Site, WorkerPerson
from app.models.identity import TempoUser, TenantMembership, UserRoleAssignment, UserSiteGrant
from app.models.mobile import LeaveRequest, NotificationJob, PushDelivery, PushDevice, ShiftOffer, SmsUsage, TenantMessaging, WorkerUserLink
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["mobile-manage"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _need(ctx: RequestContext, perm: str) -> None:
    if not ctx.has_permission(perm):
        raise AuthForbidden(f"caller lacks {perm}")


# ------------------------------------------------------------------------------------------------------------------ employee accounts
def _worker(db: Session, ctx: RequestContext, worker_id: str) -> Worker:
    w = db.get(Worker, worker_id)
    if w is None or w.tenant_id != ctx.tenant_id or w.home_site not in ctx.site_ids:
        raise RunNotFound("worker not found or not visible in caller scope")
    return w


class AppInvite(BaseModel):
    email: str | None = Field(default=None, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.post("/workers/{worker_id}/app-invite", status_code=201)
def invite_employee(worker_id: str, body: AppInvite, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Creates (or re-issues) the employee's app account and a one-time invitation. The account can only see its own worker record. Shown once."""
    _need(ctx, "labour.configure")
    w = _worker(db, ctx, worker_id)
    if w.status != "active":
        raise PolicyConflict("make the person active before inviting them to the app")
    link = db.scalar(select(WorkerUserLink).where(WorkerUserLink.tenant_id == ctx.tenant_id, WorkerUserLink.worker_id == worker_id))
    person = db.get(WorkerPerson, worker_id)
    with auth_phase(db, ctx.tenant_id):
        if link is not None:
            u = db.get(TempoUser, link.user_id)
        else:
            email = body.email.strip().lower() if body.email else None
            if email and db.scalar(select(TempoUser.user_id).where(TempoUser.email == email)):
                raise ScopeError("that email already belongs to an account; use a different address or leave it blank")
            subject = f"employee:{ctx.tenant_id}:{worker_id}"
            u = db.scalar(select(TempoUser).where(TempoUser.external_subject == subject))      # a person whose access was removed earlier is re-invited, not duplicated
            if u is None:
                u = TempoUser(external_subject=subject, email=email, display_name=person.display_name if person else None)
                db.add(u)
                db.flush()
        if u.password_hash is not None:
            token = pl.create_invitation(db, u, ctx.user_id, purpose="reset")
        else:
            token = pl.create_invitation(db, u, ctx.user_id)
    if link is None:
        m = db.get(TenantMembership, (u.user_id, ctx.tenant_id))
        if m is None:
            db.add(TenantMembership(user_id=u.user_id, tenant_id=ctx.tenant_id, is_default=True, invitation_source=f"user:{ctx.user_id}"))
        else:
            m.status = "active"
        db.add(UserRoleAssignment(user_id=u.user_id, tenant_id=ctx.tenant_id, role="employee"))
        db.add(UserSiteGrant(user_id=u.user_id, tenant_id=ctx.tenant_id, site_id=w.home_site))
        db.add(WorkerUserLink(tenant_id=ctx.tenant_id, user_id=u.user_id, worker_id=worker_id, linked_by=ctx.user_id))
    db.flush()
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="employee.app_invite", decision="allowed", session_ref=worker_id, reason_code="reissued" if link else "created", correlation_id=ctx.correlation_id)
    return {"worker_id": worker_id, "user_id": u.user_id, "invite_token": token, "invite_path": f"/invite?token={token}", "app_link": f"tempo://invite?token={token}",
            "note": "Shown once. Give it to the employee privately. It works once and expires; they set their own username and password in the app."}


@router.get("/sites/{site_id}/app-access")
def app_access(site_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx, "labour.configure")
    site = _site(db, ctx, site_id)
    workers = list(db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.home_site == site.site_id)))
    ids = [w.worker_id for w in workers] or [""]
    links = {x.worker_id: x for x in db.scalars(select(WorkerUserLink).where(WorkerUserLink.tenant_id == ctx.tenant_id, WorkerUserLink.worker_id.in_(ids)))}
    users = {u.user_id: u for u in db.scalars(select(TempoUser).where(TempoUser.user_id.in_([x.user_id for x in links.values()] or [""])))}
    devs: dict[str, int] = {}
    for d in db.scalars(select(PushDevice).where(PushDevice.tenant_id == ctx.tenant_id, PushDevice.revoked_at.is_(None), PushDevice.invalid_at.is_(None))):
        devs[d.user_id] = devs.get(d.user_id, 0) + 1
    out = {}
    for w in workers:
        l = links.get(w.worker_id)
        u = users.get(l.user_id) if l else None
        out[w.worker_id] = {"state": "not_invited" if l is None else ("active" if u and u.password_hash else "invited"), "push_devices": devs.get(l.user_id, 0) if l else 0}
    return {"site_id": site.site_id, "workers": out}


@router.get("/sites/{site_id}/offerable-workers")
def offerable_workers(site_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    """People a planner can offer a shift to: active workers at the site who have joined the app. Names need labour.worker_names."""
    _need(ctx, "labour.plan")
    site = _site(db, ctx, site_id)
    rows = db.execute(select(Worker, WorkerUserLink).join(WorkerUserLink, WorkerUserLink.worker_id == Worker.worker_id).where(Worker.tenant_id == ctx.tenant_id, Worker.home_site == site.site_id,
                                                                                                                              Worker.status == "active", WorkerUserLink.tenant_id == ctx.tenant_id)).all()
    ids = [w.worker_id for w, _ in rows] or [""]
    names = {p.worker_id: p.display_name for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == ctx.tenant_id, WorkerPerson.worker_id.in_(ids)))} if ctx.has_permission("labour.worker_names") else {}
    from app.models.canonical import SkillCertification
    skills: dict[str, list[str]] = {}
    for c in db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == ctx.tenant_id, SkillCertification.worker_id.in_(ids))):
        skills.setdefault(c.worker_id, []).append(c.skill_code)
    return sorted(({"worker_id": w.worker_id, "label": names.get(w.worker_id) or f"Worker …{w.worker_id[-4:]}", "skills": sorted(skills.get(w.worker_id, []))} for w, _ in rows), key=lambda x: x["label"])


@router.delete("/workers/{worker_id}/app-link")
def unlink_employee(worker_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Removes the employee's app access: the link, role and site access go, every session is invalidated, push devices are removed."""
    _need(ctx, "labour.configure")
    _worker(db, ctx, worker_id)
    link = db.scalar(select(WorkerUserLink).where(WorkerUserLink.tenant_id == ctx.tenant_id, WorkerUserLink.worker_id == worker_id))
    if link is None:
        raise RunNotFound("this person has no app access")
    uid = link.user_id
    db.delete(link)
    for model in (UserRoleAssignment, UserSiteGrant):
        for r in db.scalars(select(model).where(model.user_id == uid, model.tenant_id == ctx.tenant_id)):
            db.delete(r)
    for d in db.scalars(select(PushDevice).where(PushDevice.tenant_id == ctx.tenant_id, PushDevice.user_id == uid)):
        d.revoked_at, d.token = _now(), f"removed:{d.id}"
    with auth_phase(db, ctx.tenant_id):
        u = db.get(TempoUser, uid)
        if u is not None:
            u.token_version += 1   # every outstanding session for this account stops working
        m = db.get(TenantMembership, (uid, ctx.tenant_id))
        if m is not None:
            m.status = "revoked"
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="employee.app_unlink", decision="allowed", session_ref=worker_id, correlation_id=ctx.correlation_id)
    return {"worker_id": worker_id, "unlinked": True}


# ------------------------------------------------------------------------------------------------------------------ offers
class OfferIn(BaseModel):
    worker_ids: list[str] = Field(min_length=1, max_length=50)
    role: str = Field(min_length=1, max_length=60)
    zone: str = Field(min_length=1, max_length=60)
    start_at: datetime
    end_at: datetime
    break_minutes: int | None = Field(default=None, ge=0, le=180)
    instructions: str | None = Field(default=None, max_length=500)
    expires_at: datetime | None = None
    auto_confirm: bool = False

    @field_validator("start_at", "end_at", "expires_at")
    @classmethod
    def _tz(cls, d):
        if d is not None and d.tzinfo is None:
            raise ValueError("timestamps must carry a timezone offset")
        return d.astimezone(timezone.utc) if d else d


class OfferPatch(BaseModel):
    role: str | None = Field(default=None, max_length=60)
    zone: str | None = Field(default=None, max_length=60)
    start_at: datetime | None = None
    end_at: datetime | None = None
    break_minutes: int | None = Field(default=None, ge=0, le=180)
    instructions: str | None = Field(default=None, max_length=500)

    @field_validator("start_at", "end_at")
    @classmethod
    def _tz(cls, d):
        if d is not None and d.tzinfo is None:
            raise ValueError("timestamps must carry a timezone offset")
        return d.astimezone(timezone.utc) if d else d


class Note(BaseModel):
    note: str = Field(default="", max_length=300)


def _offer(db: Session, ctx: RequestContext, offer_id: str) -> ShiftOffer:
    _need(ctx, "labour.plan")
    o = db.get(ShiftOffer, offer_id)
    if o is None or o.tenant_id != ctx.tenant_id or o.site_id not in ctx.site_ids:
        raise RunNotFound("offer not found or not visible in caller scope")
    return o


@router.post("/sites/{site_id}/offers", status_code=201)
def create_offer(site_id: str, body: OfferIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx, "labour.plan")
    site = _site(db, ctx, site_id)
    o = oc.create_offer(db, ctx.tenant_id, site.site_id, ctx.user_id, role=body.role, zone=body.zone, start_at=body.start_at, end_at=body.end_at, worker_ids=body.worker_ids, break_minutes=body.break_minutes,
                        instructions=body.instructions, expires_at=body.expires_at, auto_confirm=body.auto_confirm)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="offer.create", decision="allowed", session_ref=o.id, correlation_id=ctx.correlation_id)
    return oc.offer_view(db, o, managers=True)


@router.get("/sites/{site_id}/offers")
def list_offers(site_id: str, status: str = Query(default="active", pattern="^(active|all|filled|cancelled)$"), ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    site = _site(db, ctx, site_id)
    q = select(ShiftOffer).where(ShiftOffer.tenant_id == ctx.tenant_id, ShiftOffer.site_id == site.site_id)
    if status == "active":
        q = q.where(ShiftOffer.status.in_(("open", "pending_confirmation")))
    elif status != "all":
        q = q.where(ShiftOffer.status == status)
    now = _now()
    out = []
    for o in db.scalars(q.order_by(ShiftOffer.start_at.desc()).limit(100)):
        oc._expire_if_due(o, now)
        out.append(oc.offer_view(db, o, managers=True))
    return out


@router.post("/offers/{offer_id}/confirm")
def confirm_offer(offer_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _offer(db, ctx, offer_id)
    o = oc.confirm(db, ctx.tenant_id, offer_id, ctx.user_id)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="offer.confirm", decision="allowed", session_ref=offer_id, correlation_id=ctx.correlation_id)
    return oc.offer_view(db, o, managers=True)


@router.post("/offers/{offer_id}/reject")
def reject_offer(offer_id: str, body: Note, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _offer(db, ctx, offer_id)
    o = oc.reject(db, ctx.tenant_id, offer_id, ctx.user_id, body.note)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="offer.reject", decision="allowed", session_ref=offer_id, correlation_id=ctx.correlation_id)
    return oc.offer_view(db, o, managers=True)


@router.post("/offers/{offer_id}/cancel")
def cancel_offer(offer_id: str, body: Note, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _offer(db, ctx, offer_id)
    o = oc.cancel(db, ctx.tenant_id, offer_id, ctx.user_id, body.note)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="offer.cancel", decision="allowed", session_ref=offer_id, correlation_id=ctx.correlation_id)
    return oc.offer_view(db, o, managers=True)


@router.patch("/offers/{offer_id}")
def edit_offer(offer_id: str, body: OfferPatch, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _offer(db, ctx, offer_id)
    o = oc.edit(db, ctx.tenant_id, offer_id, ctx.user_id, body.model_dump(exclude_unset=True))
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="offer.edit", decision="allowed", session_ref=offer_id, correlation_id=ctx.correlation_id)
    return oc.offer_view(db, o, managers=True)


# ------------------------------------------------------------------------------------------------------------------ leave
def _leave_window(site: Site, r: LeaveRequest) -> tuple[datetime, datetime]:
    tz = ZoneInfo(site.timezone)
    lo = datetime(r.start_date.year, r.start_date.month, r.start_date.day, tzinfo=tz).astimezone(timezone.utc)
    nxt = r.end_date + timedelta(days=1)
    return lo, datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz).astimezone(timezone.utc)


def cancel_leave_core(db: Session, r: LeaveRequest, site: Site, actor: str) -> None:
    if r.status == "cancelled":
        return
    if r.status == "rejected":
        raise PolicyConflict("this request was already declined")
    lo, _ = _leave_window(site, r)
    if r.status == "approved" and lo <= _now():
        raise PolicyConflict("this leave has already started; ask your manager")
    was_approved = r.status == "approved"
    r.status = "cancelled"
    for a in db.scalars(select(Availability).where(Availability.tenant_id == r.tenant_id, Availability.source_system == "leave_request", Availability.source_ref == r.id)):
        db.delete(a)
    auth.audit(db, actor_type="user", actor_id=actor, tenant_id=r.tenant_id, action="leave.cancel", decision="allowed", session_ref=r.id, correlation_id="n/a")
    if was_approved:
        push.notify_user(db, r.tenant_id, manager_recipients(db, r.tenant_id, r.site_id, "labour.approve"), category="decisions", kind="leave.cancelled", title="Approved leave cancelled",
                         body="An employee cancelled approved leave.", dedup_key=f"leave:{r.id}:cancelled", deep_link="/requests", site_id=r.site_id, link="/requests")


def _leave_manager_view(db: Session, r: LeaveRequest, names: dict) -> dict:
    from app.api.v1.mobile import leave_view
    site = db.get(Site, (r.tenant_id, r.site_id))
    lo, hi = _leave_window(site, r)
    clash = db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == r.tenant_id, ShiftAssignment.worker_id == r.worker_id, ShiftAssignment.status == "committed",
                                                     ShiftAssignment.start_at < hi, ShiftAssignment.end_at > lo)).all()
    return {**leave_view(r), "label": names.get(r.worker_id) or f"Worker …{r.worker_id[-4:]}", "affected_shifts": len(clash)}


@router.get("/sites/{site_id}/leave-requests")
def list_leave(site_id: str, status: str = Query(default="pending", pattern="^(pending|approved|rejected|cancelled|all)$"), ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    site = _site(db, ctx, site_id)
    q = select(LeaveRequest).where(LeaveRequest.tenant_id == ctx.tenant_id, LeaveRequest.site_id == site.site_id)
    if status != "all":
        q = q.where(LeaveRequest.status == status)
    rows = list(db.scalars(q.order_by(LeaveRequest.start_date).limit(200)))
    names = {p.worker_id: p.display_name for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == ctx.tenant_id, WorkerPerson.worker_id.in_([r.worker_id for r in rows] or [""])))} if ctx.has_permission("labour.worker_names") else {}
    return [_leave_manager_view(db, r, names) for r in rows]


class Decision(BaseModel):
    note: str = Field(default="", max_length=300)


def _decide_leave(leave_id: str, approve: bool, body: Decision, ctx: RequestContext, db: Session) -> dict:
    _need(ctx, "labour.approve")
    r = db.get(LeaveRequest, leave_id)
    if r is None or r.tenant_id != ctx.tenant_id or r.site_id not in ctx.site_ids:
        raise RunNotFound("leave request not found or not visible in caller scope")
    if r.status != "pending":
        raise PolicyConflict(f"this request is already {r.status}")
    if not approve and len(body.note.strip()) < 3:
        raise ScopeError("a reason is required to decline a request")
    site = db.get(Site, (r.tenant_id, r.site_id))
    r.status, r.decided_by, r.decided_at, r.decision_note = ("approved" if approve else "rejected"), ctx.user_id, _now(), body.note
    if approve:
        lo, hi = _leave_window(site, r)
        db.add(Availability(tenant_id=r.tenant_id, worker_id=r.worker_id, interval_start=lo, interval_end=hi, status="leave", source_system="leave_request", source_ref=r.id))
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action=f"leave.{'approve' if approve else 'reject'}", decision="allowed", session_ref=r.id, correlation_id=ctx.correlation_id)
    uid = push.user_for_worker(db, r.tenant_id, r.worker_id)
    if uid:
        push.notify_user(db, r.tenant_id, [uid], category="decisions", kind="leave.decided", title=f"Leave request {'approved' if approve else 'declined'}", body=(body.note or ""),
                         dedup_key=f"leave:{r.id}:{r.status}", deep_link=f"tempo://leave/{r.id}", site_id=r.site_id)
    names = {}
    return _leave_manager_view(db, r, names)


@router.post("/leave-requests/{leave_id}/approve")
def approve_leave(leave_id: str, body: Decision, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    return _decide_leave(leave_id, True, body, ctx, db)


@router.post("/leave-requests/{leave_id}/reject")
def reject_leave(leave_id: str, body: Decision, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    return _decide_leave(leave_id, False, body, ctx, db)


# ------------------------------------------------------------------------------------------------------------------ messaging settings and delivery tracking
class MessagingIn(BaseModel):
    push_enabled: bool
    sms_enabled: bool = False
    sms_monthly_cap: int = Field(default=0, ge=0, le=100000)
    default_reminder_lead_minutes: int = 60

    @field_validator("default_reminder_lead_minutes")
    @classmethod
    def _lead(cls, v: int) -> int:
        if v not in push.LEAD_CHOICES:
            raise ValueError("pick one of the standard reminder times")
        return v


def _messaging_out(db: Session, tenant_id: str) -> dict:
    from app.config import settings
    m = db.get(TenantMessaging, tenant_id)
    start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = db.scalar(select(func.count()).select_from(SmsUsage).where(SmsUsage.tenant_id == tenant_id, SmsUsage.status == "sent", SmsUsage.at >= start)) or 0
    return {"push_enabled": m.push_enabled if m else True, "sms_enabled": m.sms_enabled if m else False, "sms_monthly_cap": m.sms_monthly_cap if m else 0,
            "default_reminder_lead_minutes": m.default_reminder_lead_minutes if m else 60, "lead_choices": list(push.LEAD_CHOICES), "is_default": m is None,
            "push_provider": settings.push_provider, "sms_provider": settings.sms_provider, "sms_sent_this_month": used,
            "notes": ["Push provider 'disabled' means nothing is sent. Text messages are only used for urgent changes, for people who opted in, within the monthly cap, and only if no push was accepted."]}


@router.get("/messaging-settings")
def get_messaging(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx, "labour.configure")
    return _messaging_out(db, ctx.tenant_id)


@router.put("/messaging-settings")
def put_messaging(body: MessagingIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx, "labour.configure")
    m = db.get(TenantMessaging, ctx.tenant_id)
    if m is None:
        m = TenantMessaging(tenant_id=ctx.tenant_id)
        db.add(m)
    for k, v in body.model_dump().items():
        setattr(m, k, v)
    m.updated_by, m.updated_at = ctx.user_id, _now()
    db.flush()
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="messaging.settings_set", decision="allowed", reason_code=f"sms={body.sms_enabled},cap={body.sms_monthly_cap}", correlation_id=ctx.correlation_id)
    return _messaging_out(db, ctx.tenant_id)


@router.get("/messaging/deliveries")
def deliveries(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """What was attempted, what the provider said, and what the employee's device acknowledged. These are three different things."""
    _need(ctx, "labour.configure")
    since = _now() - timedelta(days=7)
    jobs: dict[str, int] = {}
    for st, n in db.execute(select(NotificationJob.status, func.count()).where(NotificationJob.tenant_id == ctx.tenant_id, NotificationJob.created_at >= since).group_by(NotificationJob.status)):
        jobs[st] = n
    dl: dict[str, int] = {}
    for st, n in db.execute(select(PushDelivery.status, func.count()).where(PushDelivery.tenant_id == ctx.tenant_id, PushDelivery.attempted_at >= since).group_by(PushDelivery.status)):
        dl[st] = n
    ack = db.scalar(select(func.count()).select_from(PushDelivery).where(PushDelivery.tenant_id == ctx.tenant_id, PushDelivery.attempted_at >= since, PushDelivery.acknowledged_at.is_not(None))) or 0
    rec = db.scalar(select(func.count()).select_from(PushDelivery).where(PushDelivery.tenant_id == ctx.tenant_id, PushDelivery.attempted_at >= since, PushDelivery.receipt_status == "ok")) or 0
    recent = [{"at": d.attempted_at, "status": d.status, "provider": d.provider, "error": d.error, "receipt": d.receipt_status, "acknowledged": d.acknowledged_at is not None}
              for d in db.scalars(select(PushDelivery).where(PushDelivery.tenant_id == ctx.tenant_id).order_by(PushDelivery.attempted_at.desc()).limit(25))]
    return {"window_days": 7, "jobs": jobs, "deliveries": dl, "provider_receipts_ok": rec, "acknowledged_by_device": ack, "recent": recent,
            "meaning": {"accepted": "the provider took the message; not proof it reached a phone", "provider_receipts_ok": "the provider says it handed the message to Apple or Google", "acknowledged_by_device": "the app reported it received or opened the notification"}}


@router.post("/messaging/run-jobs")
def run_jobs_now(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Runs this organisation's due notification jobs immediately (the same code the background loop runs)."""
    _need(ctx, "labour.configure")
    return push.process_due(db, ctx.tenant_id)
