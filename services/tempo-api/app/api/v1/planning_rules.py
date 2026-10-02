"""Planning rules: the limits a roster is generated and validated against. Saved as a new, dated policy version (older ones are kept)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import field_validator
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth
from app.core.policy import DEFAULT_CONSTRAINTS, resolve_policy
from app.solvers.shifts import DEFAULT_SHIFT_CALENDAR, calendar_from_constraints
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden
from app.models.canonical import OptimisationPolicy
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["planning"])
FIELDS = ("min_rest_hours", "max_weekly_hours", "hours_per_worker_per_day", "max_overtime_hours_per_worker_per_day", "max_consecutive_days")


class ShiftIn(BaseModel):
    code: str = Field(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=0, le=24)
    share: float | None = Field(default=None, ge=0, le=1)


class RulesIn(BaseModel):
    shift_calendar: list[ShiftIn] | None = Field(default=None, min_length=1, max_length=8)
    min_rest_hours: float = Field(ge=8, le=16)
    max_weekly_hours: float = Field(ge=20, le=60)
    hours_per_worker_per_day: float = Field(ge=4, le=12)
    max_overtime_hours_per_worker_per_day: float = Field(ge=0, le=4)
    max_consecutive_days: int = Field(ge=1, le=7)

    @field_validator("shift_calendar")
    @classmethod
    def _calendar(cls, v):
        if v is None:
            return v
        for x in v:
            if (x.end_hour - x.start_hour) % 24 == 0 and not (x.start_hour == 0 and x.end_hour == 24):
                raise ValueError(f"shift '{x.code}' must not start and end at the same hour")
        try:
            calendar_from_constraints({"shift_calendar": [x.model_dump() for x in v]})
        except ValueError as e:
            raise ValueError(str(e)) from None
        return v


def _out(db: Session, tenant_id: str) -> dict:
    p = resolve_policy(db, tenant_id)
    saved = db.scalar(select(OptimisationPolicy).where(OptimisationPolicy.tenant_id == tenant_id).order_by(OptimisationPolicy.created_at.desc()).limit(1))
    cal = [{"code": x.code, "start_hour": x.start_hour, "end_hour": x.end_hour, "share": x.share} for x in calendar_from_constraints(p.constraints)]
    return {**{k: p.constraints[k] for k in FIELDS}, "shift_calendar": cal, "shift_calendar_is_default": not p.constraints.get("shift_calendar"),
            "default_shift_calendar": [{"code": x.code, "start_hour": x.start_hour, "end_hour": x.end_hour, "share": x.share} for x in DEFAULT_SHIFT_CALENDAR], "policy_version": p.policy_version, "is_default": saved is None, "defaults": {k: DEFAULT_CONSTRAINTS[k] for k in FIELDS},
            "saved_at": saved.created_at if saved else None}


@router.get("/planning-rules")
def get_rules(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    if not ctx.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read")
    return _out(db, ctx.tenant_id)


@router.put("/planning-rules")
def put_rules(body: RulesIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Applies to rosters generated and validated from now on; published rosters are not re-checked retroactively."""
    if not ctx.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure")
    cur = resolve_policy(db, ctx.tenant_id)
    row = db.scalar(select(OptimisationPolicy).where(OptimisationPolicy.tenant_id == ctx.tenant_id).order_by(OptimisationPolicy.created_at.desc()).limit(1))
    db.add(OptimisationPolicy(policy_version=f"rules-{uuid.uuid4().hex[:10]}", tenant_id=ctx.tenant_id, jurisdiction=row.jurisdiction if row else None,
                              constraints={**(row.constraints if row else {}), **{k: v for k, v in body.model_dump().items() if v is not None}}, weights=dict(row.weights or {}) if row else {}, tolerances=dict(row.tolerances or {}) if row else {}))
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="planning.rules_set", decision="allowed",
               reason_code=",".join(f"{k}={getattr(body, k):g}" for k in FIELDS) + (f",shifts={len(body.shift_calendar)}" if body.shift_calendar else ""), session_ref=cur.policy_version, correlation_id=ctx.correlation_id)
    db.flush()
    return _out(db, ctx.tenant_id)
