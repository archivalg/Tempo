"""Internal time and attendance management (roadmap M2): site policy, supervisor daily list, missing sessions, reopening, bulk approval,
badge/PIN roster and the payroll CSV. Capture itself is in attendance.py (kiosk); single approval and corrections are in reports.py."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.operations import _site
from app.api.v1.reports import D, _default_week, approve_one
from app.core import auth, exports, timeclock
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, PolicyConflict, RunNotFound, ScopeError
from app.models.attendance import SiteGeofence, AttendancePolicy, AttendanceRevision, WorkerCredential
from app.models.canonical import AttendanceSession, Worker
from app.models.directory import WorkerPerson
from app.models.rosters import AttendanceAdjustment
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["time-attendance"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _need(ctx: RequestContext, perm: str) -> None:
    if not ctx.has_permission(perm):
        raise AuthForbidden(f"caller lacks {perm}")


# ------------------------------------------------------------------ policy
class PolicyIn(BaseModel):
    breaks_paid: bool
    rounding_minutes: int = Field(ge=0, le=30)
    rounding_mode: str = Field(pattern="^(nearest|up|down)$")
    duplicate_window_seconds: int = Field(ge=5, le=300)
    late_grace_minutes: int = Field(ge=0, le=60)
    missing_punch_after_hours: float = Field(ge=4, le=48)
    excessive_hours: float = Field(ge=6, le=24)
    location_mode: str = Field(default="off", pattern="^(off|record|require)$")

    @field_validator("rounding_minutes")
    @classmethod
    def _step(cls, v: int) -> int:
        if v not in (0, 1, 5, 6, 10, 15, 30):
            raise ValueError("rounding must be 0 (none), 1, 5, 6, 10, 15 or 30 minutes")
        return v


@router.get("/sites/{site_id}/attendance-policy")
def get_policy(site_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    saved = db.get(AttendancePolicy, (ctx.tenant_id, site.site_id))
    return timeclock.policy_dict(timeclock.get_policy(db, ctx.tenant_id, site.site_id), saved is not None)


@router.put("/sites/{site_id}/attendance-policy")
def put_policy(site_id: str, body: PolicyIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx, "labour.configure")
    site = _site(db, ctx, site_id)
    if body.location_mode != "off" and db.get(SiteGeofence, (ctx.tenant_id, site.site_id)) is None:
        raise ScopeError("set the site's geofence before turning location checking on")
    p = db.get(AttendancePolicy, (ctx.tenant_id, site.site_id))
    if p is None:
        p = AttendancePolicy(tenant_id=ctx.tenant_id, site_id=site.site_id)
        db.add(p)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    p.updated_by, p.updated_at = ctx.user_id, _now()
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="attendance.policy_set", decision="allowed", session_ref=site.site_id,
               reason_code=f"paid_breaks={body.breaks_paid},rounding={body.rounding_minutes},location={body.location_mode}", correlation_id=ctx.correlation_id)
    db.flush()
    return timeclock.policy_dict(p, True)


# ------------------------------------------------------------------ site geofence
class FenceIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_meters: float = Field(ge=25, le=5000)


@router.get("/sites/{site_id}/geofence")
def get_geofence(site_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    g = db.get(SiteGeofence, (ctx.tenant_id, site.site_id))
    return {"site_id": site.site_id, "configured": g is not None, "latitude": g.latitude if g else None, "longitude": g.longitude if g else None, "radius_meters": g.radius_meters if g else None}


@router.put("/sites/{site_id}/geofence")
def put_geofence(site_id: str, body: FenceIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """A circle round the site. Location checking (Rules) compares the kiosk's position at each punch with it."""
    _need(ctx, "labour.configure")
    site = _site(db, ctx, site_id)
    g = db.get(SiteGeofence, (ctx.tenant_id, site.site_id))
    if g is None:
        g = SiteGeofence(tenant_id=ctx.tenant_id, site_id=site.site_id, latitude=body.latitude, longitude=body.longitude, radius_meters=body.radius_meters)
        db.add(g)
    else:
        g.latitude, g.longitude, g.radius_meters = body.latitude, body.longitude, body.radius_meters
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="attendance.geofence_set", decision="allowed", session_ref=site.site_id,
               reason_code=f"radius={body.radius_meters:g}", correlation_id=ctx.correlation_id)
    db.flush()
    return {"site_id": site.site_id, "configured": True, "latitude": g.latitude, "longitude": g.longitude, "radius_meters": g.radius_meters}


# ------------------------------------------------------------------ supervisor daily list
@router.get("/sites/{site_id}/attendance/daily")
def daily(site_id: str, date: str | None = Query(default=None, pattern=D), ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    day = date or _now().astimezone(ZoneInfo(site.timezone)).date().isoformat()
    return timeclock.daily_list(db, ctx.tenant_id, site, day, _now(), can_see_names=ctx.has_permission("labour.worker_names"))


# ------------------------------------------------------------------ missing sessions and reopening
class MissingIn(BaseModel):
    worker_id: str
    start_at: datetime
    end_at: datetime
    break_minutes: float | None = Field(default=None, ge=0, le=600)
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("start_at", "end_at")
    @classmethod
    def _tz(cls, d: datetime) -> datetime:
        if d.tzinfo is None:
            raise ValueError("timestamps must carry a timezone offset")
        return d.astimezone(timezone.utc)


@router.post("/sites/{site_id}/attendance/missing-session", status_code=201)
def request_missing_session(site_id: str, body: MissingIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """The worker worked but never punched (or the kiosk was down). The request needs a second person's approval; approving it creates the
    session with correction punches as evidence."""
    _need(ctx, "labour.attendance.approve")
    site = _site(db, ctx, site_id)
    w = db.get(Worker, body.worker_id)
    if w is None or w.tenant_id != ctx.tenant_id or w.home_site != site.site_id:
        raise RunNotFound("worker not found at this site")
    if body.end_at <= body.start_at or (body.end_at - body.start_at) > timedelta(hours=16):
        raise ScopeError("a session must end after it starts and be at most 16 hours")
    if body.end_at > _now() + timedelta(minutes=5):
        raise ScopeError("a session cannot end in the future")
    if body.break_minutes is not None and body.break_minutes > (body.end_at - body.start_at).total_seconds() / 60:
        raise ScopeError("break minutes cannot exceed the session")
    clash = db.scalar(select(AttendanceSession).where(AttendanceSession.tenant_id == ctx.tenant_id, AttendanceSession.worker_id == w.worker_id,
                                                      AttendanceSession.start_at < body.end_at,
                                                      (AttendanceSession.end_at.is_(None)) | (AttendanceSession.end_at > body.start_at)).limit(1))
    if clash is not None:
        raise PolicyConflict("this worker already has attendance in that period — correct that session instead")
    a = AttendanceAdjustment(tenant_id=ctx.tenant_id, session_id=None, site_id=site.site_id, worker_id=w.worker_id, kind="add_missing", requested_start=body.start_at,
                             requested_end=body.end_at, requested_break_minutes=body.break_minutes, reason=body.reason, requested_by=ctx.user_id, original={})
    db.add(a)
    db.flush()
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="timesheet.missing_request", decision="allowed", session_ref=a.id, correlation_id=ctx.correlation_id)
    from app.core import notifications as nt
    nt.notify(db, ctx.tenant_id, nt.recipients(db, ctx.tenant_id, site.site_id, "labour.approve", {ctx.user_id}), kind="correction.requested", severity="action",
              title="Missing timesheet awaiting a decision", body=body.reason[:200], link="/approvals", site_id=site.site_id, dedup_key=f"correction:{a.id}:requested")
    return {"id": a.id, "state": a.state, "kind": a.kind}


class ReopenIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


@router.post("/attendance/sessions/{session_id}/reopen")
def reopen(session_id: str, body: ReopenIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """An approved timesheet is only changed by reopening it: that records a revision (who, when, why, and what it was) and returns it to review."""
    _need(ctx, "labour.attendance.approve")
    s = db.get(AttendanceSession, session_id)
    if s is None or s.tenant_id != ctx.tenant_id or timeclock.site_of(db, s) not in ctx.site_ids:
        raise RunNotFound("attendance session not found or not visible in caller scope")
    if s.approval != "approved":
        raise PolicyConflict("only an approved timesheet can be reopened")
    adj = db.scalars(select(AttendanceAdjustment).where(AttendanceAdjustment.tenant_id == ctx.tenant_id, AttendanceAdjustment.session_id == s.id,
                                                        AttendanceAdjustment.state == "approved").order_by(AttendanceAdjustment.requested_at.desc())).first()
    h = timeclock.hours(s, adj, timeclock.get_policy(db, ctx.tenant_id, timeclock.site_of(db, s)), _now())
    timeclock.revision(db, s, "reopened", ctx.user_id, body.reason, h)  # snapshot is the figures that WERE approved
    s.revision = (s.revision or 1) + 1
    s.approval, s.approved_by, s.approved_at = "pending", None, None
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="timesheet.reopen", decision="allowed", reason_code=body.reason[:100], session_ref=s.id, correlation_id=ctx.correlation_id)
    return {"session_id": s.id, "approval": s.approval, "revision": s.revision}


@router.get("/attendance/sessions/{session_id}/history")
def history(session_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx, "labour.read")
    s = db.get(AttendanceSession, session_id)
    if s is None or s.tenant_id != ctx.tenant_id or timeclock.site_of(db, s) not in ctx.site_ids:
        raise RunNotFound("attendance session not found or not visible in caller scope")
    from app.models.attendance import AttendancePunch
    punches = db.scalars(select(AttendancePunch).where(AttendancePunch.session_id == s.id).order_by(AttendancePunch.at, AttendancePunch.id)).all()
    revs = db.scalars(select(AttendanceRevision).where(AttendanceRevision.session_id == s.id).order_by(AttendanceRevision.at)).all()
    adjs = db.scalars(select(AttendanceAdjustment).where(AttendanceAdjustment.session_id == s.id).order_by(AttendanceAdjustment.requested_at)).all()
    return {"session_id": s.id, "revision": s.revision, "approval": s.approval,
            "punches": [{"kind": p.kind, "at": p.at, "source": p.source, "note": p.note, "location_status": p.location_status, "distance_m": p.distance_m, "accuracy_m": p.accuracy_m} for p in punches],
            "revisions": [{"revision": r.revision, "action": r.action, "actor": r.actor, "at": r.at, "reason": r.reason, "snapshot": r.snapshot} for r in revs],
            "corrections": [{"id": a.id, "state": a.state, "requested_start": a.requested_start, "requested_end": a.requested_end, "requested_break_minutes": a.requested_break_minutes,
                             "reason": a.reason, "requested_by": a.requested_by, "decided_by": a.decided_by, "decision_note": a.decision_note, "original": a.original} for a in adjs]}


class BulkIn(BaseModel):
    session_ids: list[str] = Field(min_length=1, max_length=200)


@router.post("/attendance/sessions/approve-many")
def approve_many(body: BulkIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Routine review in one pass: each session is approved on its own merits; the ones that cannot be (open, pending correction) are listed, not silently skipped."""
    _need(ctx, "labour.attendance.approve")
    approved, skipped = [], []
    for sid in dict.fromkeys(body.session_ids):
        s = db.get(AttendanceSession, sid)
        if s is None or s.tenant_id != ctx.tenant_id or timeclock.site_of(db, s) not in ctx.site_ids:
            skipped.append({"session_id": sid, "reason": "not found or not visible in caller scope"})
            continue
        try:
            with db.begin_nested():
                changed = approve_one(db, ctx, s)
        except PolicyConflict as e:
            skipped.append({"session_id": sid, "reason": str(e)})
            continue
        if changed:
            approved.append(sid)
        else:
            skipped.append({"session_id": sid, "reason": "already approved"})
    return {"approved": approved, "skipped": skipped}


# ------------------------------------------------------------------ corrections queue
@router.get("/sites/{site_id}/attendance/corrections")
def corrections(site_id: str, state: str = Query(default="pending", pattern="^(pending|approved|rejected|all)$"),
                ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    site = _site(db, ctx, site_id)
    q = select(AttendanceAdjustment).where(AttendanceAdjustment.tenant_id == ctx.tenant_id, AttendanceAdjustment.site_id == site.site_id)
    if state != "all":
        q = q.where(AttendanceAdjustment.state == state)
    rows = db.scalars(q.order_by(AttendanceAdjustment.requested_at.desc()).limit(200)).all()
    names = {p.worker_id: p.display_name for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == ctx.tenant_id, WorkerPerson.worker_id.in_([r.worker_id or "" for r in rows] or [""])))} \
        if ctx.has_permission("labour.worker_names") else {}
    return [{"id": a.id, "kind": a.kind, "state": a.state, "session_id": a.session_id, "worker_id": a.worker_id, "label": names.get(a.worker_id or "") or f"Worker …{(a.worker_id or '')[-4:]}",
             "requested_start": a.requested_start, "requested_end": a.requested_end, "requested_break_minutes": a.requested_break_minutes, "reason": a.reason, "original": a.original,
             "requested_by": a.requested_by, "requested_at": a.requested_at, "decided_by": a.decided_by, "decision_note": a.decision_note} for a in rows]


# ------------------------------------------------------------------ badge / PIN roster
@router.get("/sites/{site_id}/clock-credentials")
def clock_credentials(site_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    """Who can use the kiosk at this site. Never returns a PIN or its hash."""
    _need(ctx, "labour.configure")
    site = _site(db, ctx, site_id)
    workers = list(db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.home_site == site.site_id).order_by(Worker.worker_id)))
    ids = [w.worker_id for w in workers] or [""]
    cred = {c.worker_id: c for c in db.scalars(select(WorkerCredential).where(WorkerCredential.tenant_id == ctx.tenant_id, WorkerCredential.worker_id.in_(ids)))}
    people = {p.worker_id: p for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == ctx.tenant_id, WorkerPerson.worker_id.in_(ids)))}
    now = _now()
    from app.models.canonical import SkillCertification
    held: dict[str, list[str]] = {}
    for sc in db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == ctx.tenant_id, SkillCertification.worker_id.in_(ids))):
        held.setdefault(sc.worker_id, []).append(sc.skill_code)
    out = []
    for w in workers:
        c, p = cred.get(w.worker_id), people.get(w.worker_id)
        locked = bool(c and c.locked_until and timeclock.aware(c.locked_until) > now)
        out.append({"worker_id": w.worker_id, "label": (p.display_name if p and ctx.has_permission("labour.worker_names") else f"Worker …{w.worker_id[-4:]}"), "badge_no": p.employee_no if p else None,
                    "status": w.status, "skills": sorted(held.get(w.worker_id, [])), "has_pin": bool(c and c.pin_hash), "has_nfc": bool(c and c.nfc_tag_id), "locked": locked, "failed_attempts": c.failed_attempts if c else 0})
    return out


@router.post("/workers/{worker_id}/clock-credential/unlock")
def unlock_credential(worker_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _need(ctx, "labour.configure")
    w = db.get(Worker, worker_id)
    c = db.get(WorkerCredential, worker_id)
    if w is None or c is None or w.tenant_id != ctx.tenant_id or w.home_site not in ctx.site_ids:
        raise RunNotFound("worker credential not found or not visible in caller scope")
    c.failed_attempts, c.locked_until = 0, None
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="credential.unlock", decision="allowed", session_ref=worker_id, correlation_id=ctx.correlation_id)
    return {"worker_id": worker_id, "locked": False}


# ------------------------------------------------------------------ payroll export
def payroll_data(db: Session, ctx: RequestContext, site, start: str, days: int, now: datetime) -> dict:
    tz = ZoneInfo(site.timezone)
    d0 = datetime.fromisoformat(start).replace(tzinfo=tz)
    d1 = d0 + timedelta(days=days)
    policy = timeclock.get_policy(db, ctx.tenant_id, site.site_id)
    workers = {w.worker_id: w for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.home_site == site.site_id))}
    wids = list(workers) or [""]
    people = {p.worker_id: p for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == ctx.tenant_id, WorkerPerson.worker_id.in_(wids)))}
    sessions = list(db.scalars(select(AttendanceSession).where(AttendanceSession.tenant_id == ctx.tenant_id, AttendanceSession.worker_id.in_(wids), AttendanceSession.approval == "approved",
                                                               AttendanceSession.start_at >= d0, AttendanceSession.start_at < d1).order_by(AttendanceSession.start_at)))
    adjs = {a.session_id: a for a in db.scalars(select(AttendanceAdjustment).where(AttendanceAdjustment.tenant_id == ctx.tenant_id, AttendanceAdjustment.state == "approved",
                                                                                   AttendanceAdjustment.session_id.in_([x.id for x in sessions] or [""])).order_by(AttendanceAdjustment.requested_at))}
    rows = []
    for x in sessions:
        h = timeclock.hours(x, adjs.get(x.id), policy, now)
        p = people.get(x.worker_id)
        rows.append({"employee_no": p.employee_no if p else None, "worker_id": x.worker_id, "name": p.display_name if p and ctx.has_permission("labour.worker_names") else None,
                     "start": h["start"], "end": h["end"], "worked_hours": round(h["worked_minutes"] / 60, 2), "unpaid_break_hours": round(h["unpaid_break_minutes"] / 60, 2),
                     "payable_hours": round(h["payable_minutes"] / 60, 2), "revision": x.revision, "corrected": x.id in adjs, "rostered": x.rostered_shift_id is not None,
                     "approved_by": x.approved_by, "approved_at": x.approved_at, "session_id": x.id})
    pending = db.query(AttendanceSession).filter(AttendanceSession.tenant_id == ctx.tenant_id, AttendanceSession.worker_id.in_(wids), AttendanceSession.approval != "approved",
                                                  AttendanceSession.start_at >= d0, AttendanceSession.start_at < d1).count()
    return {"site": {"site_id": site.site_id, "name": site.name, "timezone": site.timezone}, "range": {"start": start, "days": days}, "policy": timeclock.policy_dict(policy, True),
            "rows": rows, "not_included": pending}


@router.get("/sites/{site_id}/exports/payroll-timesheets.csv")
def payroll_export(site_id: str, start: str | None = Query(default=None, pattern=D), days: int = Query(default=7, ge=1, le=31),
                   ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> Response:
    """Approved timesheets only. Hours, not pay: Tempo does not interpret awards."""
    _need(ctx, "labour.export")
    _need(ctx, "labour.attendance.approve")
    site = _site(db, ctx, site_id)
    st, now = start or _default_week(site.timezone), _now()
    body, n = exports.payroll_csv(payroll_data(db, ctx, site, st, days, now), now)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="export.payroll-timesheets", decision="allowed", reason_code=f"rows={n}", session_ref=site.site_id, correlation_id=ctx.correlation_id)
    return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="tempo-payroll-timesheets-{site.site_id}-{st}.csv"', "Cache-Control": "no-store"})
