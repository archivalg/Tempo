"""Variance, timesheets, supervised corrections and demand endpoints."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.api.v1.operations import _site
from app.core import auth, exports, reports
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, PolicyConflict, RunNotFound, ScopeError
from app.models.canonical import AttendanceSession, Worker
from app.models.rosters import AttendanceAdjustment
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["reports"])
D = r"^\d{4}-\d{2}-\d{2}$"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_week(site_tz: str) -> str:
    from zoneinfo import ZoneInfo
    from datetime import timedelta
    t = _now().astimezone(ZoneInfo(site_tz)).date()
    return (t - timedelta(days=t.weekday())).isoformat()


@router.get("/sites/{site_id}/reports/variance")
def variance(site_id: str, start: str | None = Query(default=None, pattern=D), days: int = Query(default=7, ge=1, le=14),
             ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    return reports.variance(db, ctx.tenant_id, site, start or _default_week(site.timezone), days, _now(), can_rates=ctx.has_permission("labour.rates.read"))


@router.get("/sites/{site_id}/demand")
def demand(site_id: str, start: str | None = Query(default=None, pattern=D), days: int = Query(default=7, ge=1, le=14),
           ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    return reports.demand(db, ctx.tenant_id, site, start or _default_week(site.timezone), days, _now())


@router.get("/sites/{site_id}/timesheets")
def timesheets(site_id: str, start: str | None = Query(default=None, pattern=D), days: int = Query(default=7, ge=1, le=14),
               ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    return reports.timesheets(db, ctx.tenant_id, site, start or _default_week(site.timezone), days, _now(), can_see_names=ctx.has_permission("labour.worker_names"))


def _session(db: Session, ctx: RequestContext, session_id: str) -> AttendanceSession:
    s = db.get(AttendanceSession, session_id)
    w = db.get(Worker, s.worker_id) if s else None
    if s is None or s.tenant_id != ctx.tenant_id or w is None or w.home_site not in ctx.site_ids:
        raise RunNotFound("attendance session not found or not visible in caller scope")
    return s


@router.post("/attendance/sessions/{session_id}/approve")
def approve_session(session_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    if not ctx.has_permission("labour.attendance.approve"):
        raise AuthForbidden("caller lacks labour.attendance.approve")
    s = _session(db, ctx, session_id)
    if s.end_at is None:
        raise PolicyConflict("an open session cannot be approved — the worker has not clocked out")
    pending = db.query(AttendanceAdjustment).filter_by(tenant_id=ctx.tenant_id, session_id=s.id, state="pending").first()
    if pending is not None:
        raise PolicyConflict("resolve the pending correction before approving this timesheet")
    s.approval = "approved"
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="timesheet.approve", decision="allowed", session_ref=s.id, correlation_id=ctx.correlation_id)
    return {"session_id": s.id, "approval": s.approval}


class AdjustmentIn(BaseModel):
    requested_start: datetime
    requested_end: datetime
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("requested_start", "requested_end")
    @classmethod
    def _tz(cls, d: datetime) -> datetime:
        if d.tzinfo is None:
            raise ValueError("timestamps must carry a timezone offset")
        return d.astimezone(timezone.utc)


@router.post("/attendance/sessions/{session_id}/adjustments", status_code=201)
def request_adjustment(session_id: str, body: AdjustmentIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """The original punch is never edited: a correction is a separate record that needs a second person's approval."""
    if not ctx.has_permission("labour.attendance.approve"):
        raise AuthForbidden("caller lacks labour.attendance.approve")
    s = _session(db, ctx, session_id)
    if body.requested_end <= body.requested_start or (body.requested_end - body.requested_start).total_seconds() > 16 * 3600:
        raise ScopeError("a corrected session must end after it starts and be at most 16 hours")
    if db.query(AttendanceAdjustment).filter_by(tenant_id=ctx.tenant_id, session_id=s.id, state="pending").first():
        raise PolicyConflict("a correction is already pending for this session")
    w = db.get(Worker, s.worker_id)
    a = AttendanceAdjustment(tenant_id=ctx.tenant_id, session_id=s.id, site_id=w.home_site, requested_start=body.requested_start, requested_end=body.requested_end,
                             reason=body.reason, requested_by=ctx.user_id)
    db.add(a)
    db.flush()
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="timesheet.adjust_request", decision="allowed", session_ref=a.id, correlation_id=ctx.correlation_id)
    return {"id": a.id, "state": a.state, "session_id": s.id}


class Decide(BaseModel):
    note: str = Field(default="", max_length=500)


def _decide(state: str):
    def h(adjustment_id: str, body: Decide, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
        if not ctx.has_permission("labour.approve"):
            raise AuthForbidden("caller lacks labour.approve")
        a = db.get(AttendanceAdjustment, adjustment_id)
        if a is None or a.tenant_id != ctx.tenant_id or a.site_id not in ctx.site_ids:
            raise RunNotFound("correction not found or not visible in caller scope")
        if a.state != "pending":
            raise PolicyConflict(f"correction is already {a.state}")
        if a.requested_by == ctx.user_id:
            raise AuthForbidden("the requester cannot decide their own correction")
        if state == "rejected" and len(body.note.strip()) < 3:
            raise ScopeError("a reason is required to reject a correction")
        a.state, a.decided_by, a.decided_at, a.decision_note = state, ctx.user_id, datetime.now(timezone.utc), body.note
        auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action=f"timesheet.adjust_{state}", decision="allowed", session_ref=a.id, correlation_id=ctx.correlation_id)
        return {"id": a.id, "state": a.state}
    return h


router.post("/attendance/adjustments/{adjustment_id}/approve")(_decide("approved"))
router.post("/attendance/adjustments/{adjustment_id}/reject")(_decide("rejected"))


@router.get("/sites/{site_id}/exports/{kind}.csv")
def export_csv(kind: str, site_id: str, start: str | None = Query(default=None, pattern=D), days: int = Query(default=7, ge=1, le=14),
               ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> Response:
    """Same data, same permission filters as the screens; the file is audited with its row count."""
    if not ctx.has_permission("labour.export"):
        raise AuthForbidden("caller lacks labour.export")
    if kind not in ("variance", "timesheets", "demand"):
        raise RunNotFound("unknown export")
    site = _site(db, ctx, site_id)
    st, now = start or _default_week(site.timezone), _now()
    if kind == "variance":
        body, n = exports.variance_csv(reports.variance(db, ctx.tenant_id, site, st, days, now, can_rates=ctx.has_permission("labour.rates.read")), now)
    elif kind == "timesheets":
        body, n = exports.timesheets_csv(reports.timesheets(db, ctx.tenant_id, site, st, days, now, can_see_names=ctx.has_permission("labour.worker_names")), now)
    else:
        body, n = exports.demand_csv(reports.demand(db, ctx.tenant_id, site, st, days, now), now)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action=f"export.{kind}", decision="allowed", reason_code=f"rows={n}", session_ref=site.site_id, correlation_id=ctx.correlation_id)
    return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="tempo-{kind}-{site.site_id}-{st}.csv"', "Cache-Control": "no-store"})
