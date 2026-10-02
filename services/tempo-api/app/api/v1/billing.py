"""What a customer can see about their own plan and allowance."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import subscription as sub
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden
from app.models.billing import SubscriptionEvent
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["billing"])


@router.get("/billing/plan")
def my_plan(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    if not ctx.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read")
    out = sub.describe(db, ctx.tenant_id)
    if out["managed"]:
        out["history"] = [{"at": e.at, "action": e.action, "reason": e.reason} for e in db.scalars(
            select(SubscriptionEvent).where(SubscriptionEvent.tenant_id == ctx.tenant_id).order_by(SubscriptionEvent.at.desc()).limit(20))]
    return out
