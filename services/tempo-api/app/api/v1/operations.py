"""Operations read APIs behind Overview / Roster Planner / Live Attendance, and the exception lifecycle.

Every route resolves the site through the caller's finite site grants first: a site outside the
grant set is a non-enumerating 404, exactly like a nonexistent one.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth, opsview
from app.core.exceptions_engine import STATUS_OPEN, detect_exceptions
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, RunNotFound, ScopeError
from app.models.directory import ExceptionCase, Site
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["operations"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _site(db: Session, ctx: RequestContext, site_id: str) -> Site:
    if not ctx.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read")
    site = opsview.get_site(db, ctx.tenant_id, site_id, ctx.site_ids)
    if site is None:
        raise RunNotFound(f"site '{site_id}' not found or not visible in caller scope")
    return site


@router.get("/sites")
def list_sites(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    if not ctx.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read")
    now = _now()
    out = []
    for s in db.scalars(select(Site).where(Site.tenant_id == ctx.tenant_id, Site.site_id.in_(list(ctx.site_ids))).order_by(Site.name)):
        srcs = opsview.site_sources(db, ctx.tenant_id, s.site_id, now)
        out.append({"site_id": s.site_id, "name": s.name, "timezone": s.timezone, "operating_mode": s.operating_mode, "is_synthetic": s.is_synthetic,
                    "data_sources": srcs, "all_sources_fresh": all(x["fresh"] for x in srcs) if srcs else False})
    return out


@router.get("/sites/{site_id}/overview")
def site_overview(site_id: str, date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
                  ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    return opsview.overview(db, ctx.tenant_id, site, date, _now(), can_see_rates=ctx.has_permission("labour.rates.read"),
                            can_see_names=ctx.has_permission("labour.worker_names"))


@router.get("/sites/{site_id}/roster")
def site_roster(site_id: str, start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"), days: int = Query(default=7, ge=1, le=14),
                view: str | None = Query(default=None, pattern="^(published|draft)$"),
                ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    return opsview.roster_week(db, ctx.tenant_id, site, start, days, _now(), can_see_rates=ctx.has_permission("labour.rates.read"),
                               can_see_names=ctx.has_permission("labour.worker_names"), view=view)


@router.get("/sites/{site_id}/attendance/live")
def site_attendance_live(site_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    return opsview.live_attendance(db, ctx.tenant_id, site, _now(), can_see_names=ctx.has_permission("labour.worker_names"))


@router.post("/sites/{site_id}/exceptions/detect")
def run_detection(site_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    site = _site(db, ctx, site_id)
    if not ctx.has_permission("labour.exception.manage"):
        raise AuthForbidden("caller lacks labour.exception.manage")
    return {"site_id": site.site_id, "new_cases": detect_exceptions(db, ctx.tenant_id, site.site_id, _now())}


def _case(db: Session, ctx: RequestContext, exception_id: str) -> ExceptionCase:
    if not ctx.has_permission("labour.exception.manage"):
        raise AuthForbidden("caller lacks labour.exception.manage")
    e = db.get(ExceptionCase, exception_id)
    if e is None or e.tenant_id != ctx.tenant_id or e.site_id not in ctx.site_ids:
        raise RunNotFound("exception not found or not visible in caller scope")
    return e


class Resolution(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/exceptions/{exception_id}/acknowledge")
def acknowledge(exception_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    e = _case(db, ctx, exception_id)
    if e.state == "detected":
        e.state = "triaged"
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="exception.acknowledge", decision="allowed",
               session_ref=e.id, correlation_id=ctx.correlation_id)
    return {"id": e.id, "state": e.state}


@router.post("/exceptions/{exception_id}/assign")
def assign(exception_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Assign to the caller (self-assign). Assigning to others arrives with user directory APIs."""
    e = _case(db, ctx, exception_id)
    if e.state not in STATUS_OPEN:
        raise ScopeError("exception is already closed")
    e.state, e.owner_user_id = "assigned", ctx.user_id
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="exception.assign", decision="allowed",
               session_ref=e.id, correlation_id=ctx.correlation_id)
    return {"id": e.id, "state": e.state, "owner_user_id": e.owner_user_id}


def _close(state: str, action: str):
    def handler(exception_id: str, body: Resolution, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
        e = _case(db, ctx, exception_id)
        if e.state not in STATUS_OPEN:
            raise ScopeError("exception is already closed")
        e.state, e.resolution, e.resolved_at = state, body.reason, _now()
        auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action=action, decision="allowed",
                   session_ref=e.id, correlation_id=ctx.correlation_id)
        return {"id": e.id, "state": e.state, "resolution": e.resolution}
    return handler


router.post("/exceptions/{exception_id}/resolve")(_close("resolved", "exception.resolve"))
router.post("/exceptions/{exception_id}/dismiss")(_close("dismissed", "exception.dismiss"))
