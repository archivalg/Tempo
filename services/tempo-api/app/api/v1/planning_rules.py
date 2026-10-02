"""Planning rules: the limits a roster is generated and validated against. Saved as a new, dated policy version (older ones are kept)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth
from app.core.policy import DEFAULT_CONSTRAINTS, resolve_policy
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden
from app.models.canonical import OptimisationPolicy
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["planning"])
FIELDS = ("min_rest_hours", "max_weekly_hours", "hours_per_worker_per_day", "max_overtime_hours_per_worker_per_day", "max_consecutive_days")


class RulesIn(BaseModel):
    min_rest_hours: float = Field(ge=8, le=16)
    max_weekly_hours: float = Field(ge=20, le=60)
    hours_per_worker_per_day: float = Field(ge=4, le=12)
    max_overtime_hours_per_worker_per_day: float = Field(ge=0, le=4)
    max_consecutive_days: int = Field(ge=1, le=7)


def _out(db: Session, tenant_id: str) -> dict:
    p = resolve_policy(db, tenant_id)
    saved = db.scalar(select(OptimisationPolicy).where(OptimisationPolicy.tenant_id == tenant_id).order_by(OptimisationPolicy.created_at.desc()).limit(1))
    return {**{k: p.constraints[k] for k in FIELDS}, "policy_version": p.policy_version, "is_default": saved is None, "defaults": {k: DEFAULT_CONSTRAINTS[k] for k in FIELDS},
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
                              constraints={**(row.constraints if row else {}), **body.model_dump()}, weights=dict(row.weights or {}) if row else {}, tolerances=dict(row.tolerances or {}) if row else {}))
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="planning.rules_set", decision="allowed",
               reason_code=",".join(f"{k}={getattr(body, k):g}" for k in FIELDS), session_ref=cur.policy_version, correlation_id=ctx.correlation_id)
    db.flush()
    return _out(db, ctx.tenant_id)
