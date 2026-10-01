"""Demand overrides: reasoned, expiring adjustments on top of the statistical forecast."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1 import runs as runs_api
from app.api.v1.operations import _site
from app.core import auth, overrides, rosters as svc
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, PolicyConflict, RunNotFound, ScopeError
from app.models.rosters import DemandOverride
from app.models.directory import Site
from app.schemas.runs import RunRequest
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["demand"])
D = r"^\d{4}-\d{2}-\d{2}$"


class OverrideIn(BaseModel):
    activity: str | None = Field(default=None, max_length=80)
    start_date: str = Field(pattern=D)
    end_date: str = Field(pattern=D)
    mode: str
    value: float
    reason: str = Field(max_length=500)
    expires_at: datetime

    @field_validator("expires_at")
    @classmethod
    def _tz(cls, d: datetime) -> datetime:
        if d.tzinfo is None:
            raise ValueError("expires_at must carry a timezone offset")
        return d.astimezone(timezone.utc)


class Revoke(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


def _rerun_forecast(db: Session, ctx: RequestContext, site: Site, start_date: str, end_date: str) -> str | None:
    """Overrides take effect when a forecast is produced, so every change immediately produces one for the dates it touches."""
    days = (datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)).days + 1
    start, end = svc.window(site, start_date, days)
    req = RunRequest(**{"request_id": f"req_{uuid.uuid4().hex[:12]}",
                        "scope": {"tenant_id": ctx.tenant_id, "site_ids": [site.site_id], "customer_ids": list(ctx.customer_ids)},
                        "planning_window": {"start": start.isoformat().replace("+00:00", "Z"), "end": end.isoformat().replace("+00:00", "Z"), "timezone": site.timezone, "bucket_minutes": 1440},
                        "configuration": {}})
    run = runs_api.create_run("demand_forecast", req, ctx, str(uuid.uuid4()), db)
    return run.run_id


@router.get("/sites/{site_id}/demand/overrides")
def list_overrides(site_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    site = _site(db, ctx, site_id)
    now = datetime.now(timezone.utc)
    rows = db.scalars(select(DemandOverride).where(DemandOverride.tenant_id == ctx.tenant_id, DemandOverride.site_id == site.site_id).order_by(DemandOverride.created_at.desc()).limit(100))
    return [overrides.serialise(o, now) for o in rows]


@router.post("/sites/{site_id}/demand/overrides", status_code=201)
def create_override(site_id: str, body: OverrideIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    if not ctx.has_permission("labour.plan"):
        raise AuthForbidden("caller lacks labour.plan")
    site = _site(db, ctx, site_id)
    now = datetime.now(timezone.utc)
    problem = overrides.validate(body.mode, body.value, body.start_date, body.end_date, body.reason, body.expires_at, now)
    if problem:
        raise ScopeError(problem)
    for o in overrides.active_for(db, ctx.tenant_id, site.site_id, now):
        if o.activity == body.activity and not (o.end_date < body.start_date or o.start_date > body.end_date):
            raise PolicyConflict("an active override already covers some of these dates for this activity — revoke it first so adjustments never stack silently")
    o = DemandOverride(tenant_id=ctx.tenant_id, site_id=site.site_id, activity=body.activity, start_date=body.start_date, end_date=body.end_date, mode=body.mode,
                       value=body.value, reason=body.reason.strip(), expires_at=body.expires_at, created_by=ctx.user_id)
    db.add(o)
    db.flush()
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="demand.override_create", decision="allowed", session_ref=o.id, correlation_id=ctx.correlation_id)
    run_id = _rerun_forecast(db, ctx, site, body.start_date, body.end_date)
    return {**overrides.serialise(o, now), "forecast_run_id": run_id}


@router.post("/demand/overrides/{override_id}/revoke")
def revoke_override(override_id: str, body: Revoke, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    if not ctx.has_permission("labour.plan"):
        raise AuthForbidden("caller lacks labour.plan")
    o = db.get(DemandOverride, override_id)
    if o is None or o.tenant_id != ctx.tenant_id or o.site_id not in ctx.site_ids:
        raise RunNotFound("override not found or not visible in caller scope")
    if o.state != "active":
        raise PolicyConflict(f"override is already {o.state}")
    now = datetime.now(timezone.utc)
    o.state, o.revoked_by, o.revoked_at, o.revoke_reason = "revoked", ctx.user_id, now, body.reason
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="demand.override_revoke", decision="allowed", session_ref=o.id, correlation_id=ctx.correlation_id)
    db.flush()
    site = _site(db, ctx, o.site_id)
    run_id = _rerun_forecast(db, ctx, site, o.start_date, o.end_date)
    return {**overrides.serialise(o, now), "forecast_run_id": run_id}
