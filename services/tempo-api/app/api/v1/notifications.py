"""A user's own notifications. Always filtered to the caller; there is no way to read someone else's."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import notifications as nt
from app.dependencies import get_db, get_request_context
from app.errors import RunNotFound
from app.models.rosters import Notification
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["notifications"])


def _mine(ctx: RequestContext):
    return (Notification.tenant_id == ctx.tenant_id, Notification.user_id == ctx.user_id)


@router.get("/notifications")
def list_notifications(unread: bool = False, limit: int = Query(default=30, ge=1, le=100), ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    q = select(Notification).where(*_mine(ctx))
    if unread:
        q = q.where(Notification.read_at.is_(None))
    items = db.scalars(q.order_by(Notification.created_at.desc()).limit(limit)).all()
    count = db.scalar(select(func.count()).select_from(Notification).where(*_mine(ctx), Notification.read_at.is_(None))) or 0
    return {"unread": count, "items": [nt.serialise(n) for n in items]}


@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    n = db.scalar(select(Notification).where(*_mine(ctx), Notification.id == notification_id))
    if n is None:
        raise RunNotFound("notification not found")
    n.read_at = n.read_at or datetime.now(timezone.utc)
    return nt.serialise(n)


@router.post("/notifications/read-all")
def mark_all_read(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    res = db.execute(update(Notification).where(*_mine(ctx), Notification.read_at.is_(None)).values(read_at=datetime.now(timezone.utc)))
    return {"marked": res.rowcount}
