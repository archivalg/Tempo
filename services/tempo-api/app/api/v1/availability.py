"""Worker availability entered in Tempo: unavailable, leave or rostered day off. The roster board treats these as hard conflicts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.operations import _site
from app.core import auth
from app.core.rosters import window
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, PolicyConflict, RunNotFound, ScopeError
from app.models.canonical import Availability, Worker
from app.models.directory import WorkerPerson
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["planning"])
D = r"^\d{4}-\d{2}-\d{2}$"
STATUSES = ("unavailable", "leave", "rdo")


class AvailabilityIn(BaseModel):
    worker_id: str
    start_at: datetime
    end_at: datetime
    status: str = Field(pattern="^(unavailable|leave|rdo)$")

    @field_validator("start_at", "end_at")
    @classmethod
    def _tz(cls, d: datetime) -> datetime:
        if d.tzinfo is None:
            raise ValueError("timestamps must carry a timezone offset")
        return d.astimezone(timezone.utc)


def _row(a: Availability, label: str) -> dict:
    return {"id": a.id, "worker_id": a.worker_id, "label": label, "start_at": a.interval_start, "end_at": a.interval_end, "status": a.status,
            "source": a.source_system, "editable": a.source_system == "tempo_native"}


@router.get("/sites/{site_id}/availability")
def list_availability(site_id: str, start: str = Query(pattern=D), days: int = Query(default=14, ge=1, le=60), ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    site = _site(db, ctx, site_id)
    ws, we = window(site, start, days)
    workers = {w.worker_id for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.home_site == site.site_id))}
    names = {p.worker_id: p.display_name for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == ctx.tenant_id, WorkerPerson.worker_id.in_(workers or [""])))} if ctx.has_permission("labour.worker_names") else {}
    rows = db.scalars(select(Availability).where(Availability.tenant_id == ctx.tenant_id, Availability.worker_id.in_(workers or [""]), Availability.interval_end > ws,
                                                 Availability.interval_start < we, Availability.status.in_(STATUSES)).order_by(Availability.interval_start)).all()
    return [_row(a, names.get(a.worker_id) or f"Worker …{a.worker_id[-4:]}") for a in rows]


@router.post("/sites/{site_id}/availability", status_code=201)
def add_availability(site_id: str, body: AvailabilityIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    if not ctx.has_permission("labour.plan"):
        raise AuthForbidden("caller lacks labour.plan")
    site = _site(db, ctx, site_id)
    w = db.get(Worker, body.worker_id)
    if w is None or w.tenant_id != ctx.tenant_id or w.home_site != site.site_id:
        raise ScopeError("worker is not eligible at this site")
    if body.end_at <= body.start_at or body.end_at - body.start_at > timedelta(days=60):
        raise ScopeError("the period must end after it starts and be at most 60 days")
    clash = db.scalar(select(Availability).where(Availability.tenant_id == ctx.tenant_id, Availability.worker_id == w.worker_id, Availability.status == body.status,
                                                 Availability.interval_start < body.end_at, Availability.interval_end > body.start_at).limit(1))
    if clash is not None:
        raise PolicyConflict("this worker already has the same kind of entry overlapping that period")
    a = Availability(tenant_id=ctx.tenant_id, worker_id=w.worker_id, interval_start=body.start_at, interval_end=body.end_at, status=body.status, source_system="tempo_native")
    db.add(a)
    db.flush()
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="availability.add", decision="allowed", reason_code=body.status, session_ref=a.id, correlation_id=ctx.correlation_id)
    return _row(a, f"Worker …{w.worker_id[-4:]}")


@router.delete("/availability/{availability_id}")
def remove_availability(availability_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    if not ctx.has_permission("labour.plan"):
        raise AuthForbidden("caller lacks labour.plan")
    a = db.get(Availability, availability_id)
    w = db.get(Worker, a.worker_id) if a else None
    if a is None or a.tenant_id != ctx.tenant_id or w is None or w.home_site not in ctx.site_ids:
        raise RunNotFound("entry not found or not visible in caller scope")
    if a.source_system != "tempo_native":
        raise PolicyConflict("this entry came from another system; change it there")
    db.delete(a)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="availability.remove", decision="allowed", reason_code=a.status, session_ref=a.id, correlation_id=ctx.correlation_id)
    return {"id": availability_id, "removed": True}
