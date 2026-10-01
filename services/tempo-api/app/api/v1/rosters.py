"""Roster version workflow endpoints. See app/core/rosters.py for the rules these enforce."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1 import runs as runs_api
from app.core import rosters as svc
from app.dependencies import get_db, get_request_context
from app.errors import PolicyConflict, ScopeError
from app.models.canonical import OptimisationPolicy, ShiftAssignment, Worker
from app.models.rosters import RosterEvent, RosterVersion
from app.schemas.runs import RunRequest
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["rosters"])
LOCAL_DATE = r"^\d{4}-\d{2}-\d{2}$"


def _site(db: Session, ctx: RequestContext, site_id: str):
    from app.api.v1.operations import _site as site_of
    return site_of(db, ctx, site_id)


class Generate(BaseModel):
    week_start: str = Field(pattern=LOCAL_DATE)
    days: int = Field(default=7, ge=1, le=14)
    policy_version: str | None = None


@router.post("/sites/{site_id}/rosters/generate", status_code=201)
def generate(site_id: str, body: Generate, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Runs the named-roster solver for the window and stores the result as a new draft version."""
    site = _site(db, ctx, site_id)
    svc.require(ctx, "labour.plan")
    start, end = svc.window(site, body.week_start, body.days)
    workers = [w.worker_id for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.home_site == site_id))]
    # retire loose proposals from earlier un-versioned runs so the new draft is the only proposal
    for sh in db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == ctx.tenant_id, ShiftAssignment.worker_id.in_(workers or [""]),
                                                       ShiftAssignment.status == "proposed", ShiftAssignment.source_ref.is_(None))):
        sh.status = "superseded"
    policy = body.policy_version or db.scalar(select(OptimisationPolicy.policy_version).where(OptimisationPolicy.tenant_id == ctx.tenant_id)
                                              .order_by(OptimisationPolicy.created_at.desc()).limit(1))
    req = RunRequest(**{
        "request_id": f"req_{uuid.uuid4().hex[:12]}",
        "scope": {"tenant_id": ctx.tenant_id, "site_ids": [site_id], "customer_ids": list(ctx.customer_ids)},
        "planning_window": {"start": start.isoformat().replace("+00:00", "Z"), "end": end.isoformat().replace("+00:00", "Z"), "timezone": site.timezone, "bucket_minutes": 1440},
        "configuration": {"policy_version": policy} if policy else {},
    })
    # Persist the forecast this roster is built on (reproducible evidence; the Demand/Overview/coverage views read it).
    runs_api.create_run("demand_forecast", req.model_copy(update={"request_id": f"req_{uuid.uuid4().hex[:12]}"}), ctx, str(uuid.uuid4()), db)
    run = runs_api.create_run("named_roster", req, ctx, str(uuid.uuid4()), db)
    v = RosterVersion(tenant_id=ctx.tenant_id, site_id=site_id, week_start=body.week_start, days=body.days, version_no=svc.next_version_no(db, ctx, site_id, body.week_start),
                      source="solver", source_run_id=run.run_id, created_by=ctx.user_id)
    db.add(v)
    db.flush()
    new_rows = list(db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == ctx.tenant_id, ShiftAssignment.worker_id.in_(workers or [""]),
                                                              ShiftAssignment.status == "proposed", ShiftAssignment.source_ref.is_(None))))
    for sh in new_rows:
        sh.source_ref = v.id
    svc.retire_open_drafts(db, ctx, site_id, body.week_start, keep=v.id)
    svc.event(db, ctx, v, "generated", {"run_id": run.run_id, "shifts": len(new_rows), "policy": policy, "run_status": run.status})
    db.flush()
    return svc.board(db, ctx, site, v)


@router.post("/sites/{site_id}/rosters/copy-published", status_code=201)
def copy_published(site_id: str, body: Generate, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Manager adjustment starts from what is live: clone the published shifts into a fresh editable draft."""
    site = _site(db, ctx, site_id)
    svc.require(ctx, "labour.plan")
    start, end = svc.window(site, body.week_start, body.days)
    workers = [w.worker_id for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.home_site == site_id))]
    src = list(db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == ctx.tenant_id, ShiftAssignment.worker_id.in_(workers or [""]),
                                                        ShiftAssignment.status == "committed", ShiftAssignment.start_at >= start, ShiftAssignment.start_at < end)))
    if not src:
        raise PolicyConflict("nothing is published for that week to copy")
    parent = db.scalar(select(RosterVersion.id).where(RosterVersion.tenant_id == ctx.tenant_id, RosterVersion.site_id == site_id, RosterVersion.week_start == body.week_start,
                                                     RosterVersion.state.in_(("published", "reconciled"))).order_by(RosterVersion.version_no.desc()).limit(1))
    v = RosterVersion(tenant_id=ctx.tenant_id, site_id=site_id, week_start=body.week_start, days=body.days, version_no=svc.next_version_no(db, ctx, site_id, body.week_start),
                      source="copy_of_published", parent_version_id=parent, created_by=ctx.user_id)
    db.add(v)
    db.flush()
    for s in src:
        db.add(ShiftAssignment(tenant_id=ctx.tenant_id, worker_id=s.worker_id, role=s.role, zone=s.zone, start_at=s.start_at, end_at=s.end_at, status="proposed",
                               source_system="tempo_native", source_ref=v.id))
    svc.retire_open_drafts(db, ctx, site_id, body.week_start, keep=v.id)
    svc.event(db, ctx, v, "copied_from_published", {"shifts": len(src), "parent": parent})
    db.flush()
    return svc.board(db, ctx, site, v)


@router.get("/sites/{site_id}/rosters")
def list_versions(site_id: str, week_start: str | None = Query(default=None, pattern=LOCAL_DATE), ctx: RequestContext = Depends(get_request_context),
                  db: Session = Depends(get_db)) -> list[dict]:
    _site(db, ctx, site_id)
    q = select(RosterVersion).where(RosterVersion.tenant_id == ctx.tenant_id, RosterVersion.site_id == site_id)
    if week_start:
        q = q.where(RosterVersion.week_start == week_start)
    return [svc.serialise(v) for v in db.scalars(q.order_by(RosterVersion.created_at.desc()).limit(50))]


@router.get("/rosters/pending")
def pending(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    """Approvals inbox: rosters awaiting a decision at the caller's sites, with the impact the approver must see."""
    svc.require(ctx, "labour.read")
    out = []
    for v in db.scalars(select(RosterVersion).where(RosterVersion.tenant_id == ctx.tenant_id, RosterVersion.site_id.in_(list(ctx.site_ids)),
                                                    RosterVersion.state.in_(("pending_approval", "approved"))).order_by(RosterVersion.submitted_at)):
        from app.models.directory import Site
        site = db.get(Site, (ctx.tenant_id, v.site_id))
        out.append({**svc.serialise(v), "site_name": site.name if site else v.site_id,
                    "age_seconds": int((datetime.now(timezone.utc) - (v.submitted_at or v.created_at).replace(tzinfo=timezone.utc)).total_seconds()),
                    "impact": svc.impact(db, ctx, site, v) if site else None})
    return out


@router.get("/rosters/{version_id}")
def get_roster(version_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    svc.require(ctx, "labour.read")
    v = svc.get_version(db, ctx, version_id)
    return svc.board(db, ctx, _site(db, ctx, v.site_id), v)


@router.get("/rosters/{version_id}/events")
def events(version_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    svc.require(ctx, "labour.read")
    v = svc.get_version(db, ctx, version_id)
    return [{"at": e.at, "actor": e.actor_user_id, "action": e.action, "detail": e.detail} for e in db.scalars(
        select(RosterEvent).where(RosterEvent.tenant_id == ctx.tenant_id, RosterEvent.version_id == v.id).order_by(RosterEvent.at))]


class ShiftIn(BaseModel):
    worker_id: str
    role: str = Field(min_length=1, max_length=40)
    zone: str = Field(min_length=1, max_length=40)
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def _aware(cls, d: datetime) -> datetime:
        if d.tzinfo is None:
            raise ValueError("timestamps must carry a timezone offset")
        return d.astimezone(timezone.utc)


class ShiftPatch(BaseModel):
    worker_id: str | None = None
    role: str | None = None
    zone: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None


def _check_times(site, v: RosterVersion, start: datetime, end: datetime) -> None:
    ws, we = svc.window(site, v.week_start, v.days)
    if end <= start or (end - start) > timedelta(hours=16):
        raise ScopeError("a shift must end after it starts and be at most 16 hours")
    if start < ws - timedelta(hours=12) or start >= we:
        raise ScopeError("shift start is outside this roster's window")


def _editable(db: Session, ctx: RequestContext, version_id: str):
    svc.require(ctx, "labour.plan")
    v = svc.get_version(db, ctx, version_id)
    svc.check_editable(v)
    return v, _site(db, ctx, v.site_id)


@router.post("/rosters/{version_id}/shifts", status_code=201)
def add_shift(version_id: str, body: ShiftIn, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    v, site = _editable(db, ctx, version_id)
    svc.worker_at_site(db, ctx, v.site_id, body.worker_id)
    _check_times(site, v, body.start_at, body.end_at)
    svc.invalidate_if_needed(db, ctx, v)
    sh = ShiftAssignment(tenant_id=ctx.tenant_id, worker_id=body.worker_id, role=body.role, zone=body.zone, start_at=body.start_at, end_at=body.end_at,
                         status="proposed", source_system="tempo_native", source_ref=v.id)
    db.add(sh)
    db.flush()
    svc.event(db, ctx, v, "shift_added", {"shift_id": sh.shift_id, "worker_id": body.worker_id, "role": body.role, "zone": body.zone,
                                          "start": body.start_at.isoformat(), "end": body.end_at.isoformat()})
    return svc.board(db, ctx, site, v)


def _shift(db: Session, ctx: RequestContext, v: RosterVersion, shift_id: str) -> ShiftAssignment:
    sh = db.get(ShiftAssignment, shift_id)
    if sh is None or sh.tenant_id != ctx.tenant_id or sh.source_ref != v.id:
        from app.errors import RunNotFound
        raise RunNotFound("shift not found in this roster version")
    return sh


@router.patch("/rosters/{version_id}/shifts/{shift_id}")
def edit_shift(version_id: str, shift_id: str, body: ShiftPatch, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    v, site = _editable(db, ctx, version_id)
    sh = _shift(db, ctx, v, shift_id)
    before = {"worker_id": sh.worker_id, "role": sh.role, "zone": sh.zone, "start": svc._aware(sh.start_at).isoformat(), "end": svc._aware(sh.end_at).isoformat()}
    start, end = (body.start_at or sh.start_at), (body.end_at or sh.end_at)
    start, end = start.astimezone(timezone.utc) if start.tzinfo else start.replace(tzinfo=timezone.utc), end.astimezone(timezone.utc) if end.tzinfo else end.replace(tzinfo=timezone.utc)
    if body.worker_id:
        svc.worker_at_site(db, ctx, v.site_id, body.worker_id)
    _check_times(site, v, start, end)
    svc.invalidate_if_needed(db, ctx, v)
    sh.worker_id, sh.role, sh.zone = body.worker_id or sh.worker_id, body.role or sh.role, body.zone or sh.zone
    sh.start_at, sh.end_at = start, end
    db.flush()
    svc.event(db, ctx, v, "shift_edited", {"shift_id": shift_id, "before": before, "after": {"worker_id": sh.worker_id, "role": sh.role, "zone": sh.zone, "start": start.isoformat(), "end": end.isoformat()}})
    return svc.board(db, ctx, site, v)


@router.delete("/rosters/{version_id}/shifts/{shift_id}")
def delete_shift(version_id: str, shift_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    v, site = _editable(db, ctx, version_id)
    sh = _shift(db, ctx, v, shift_id)
    svc.invalidate_if_needed(db, ctx, v)
    svc.event(db, ctx, v, "shift_removed", {"shift_id": shift_id, "worker_id": sh.worker_id, "role": sh.role, "start": svc._aware(sh.start_at).isoformat()})
    db.delete(sh)
    db.flush()
    return svc.board(db, ctx, site, v)


@router.post("/rosters/{version_id}/validate")
def validate(version_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """Human-readable impact + the payload hash approval will bind to. Expires so a stale validation cannot be replayed."""
    svc.require(ctx, "labour.read")
    v = svc.get_version(db, ctx, version_id)
    site = _site(db, ctx, v.site_id)
    shifts = svc.version_shifts(db, v)
    b = svc.board(db, ctx, site, v)
    return {"version_id": v.id, "state": v.state, "shifts": len(shifts), "hard_conflicts": b["hard_conflicts"], "conflicts": b["conflicts"][:100],
            "can_submit": b["hard_conflicts"] == 0 and len(shifts) > 0, "payload_hash": svc.payload_hash(shifts),
            "impact": {"this_version": b["totals"]["draft"] if v.state not in ("published", "reconciled") else b["totals"]["published"], "current_published": b["totals"]["published"]},
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=15)}


@router.post("/rosters/{version_id}/submit")
def submit(version_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    svc.require(ctx, "labour.plan")
    v = svc.get_version(db, ctx, version_id)
    if v.state != "draft":
        raise PolicyConflict(f"only a draft can be submitted (this is {v.state})")
    site = _site(db, ctx, v.site_id)
    shifts = svc.version_shifts(db, v)
    b = svc.board(db, ctx, site, v)
    if not shifts:
        raise PolicyConflict("an empty roster cannot be submitted")
    if b["hard_conflicts"]:
        raise PolicyConflict(f"{b['hard_conflicts']} unresolved hard conflict(s) — fix them before submitting")
    v.state, v.payload_hash, v.submitted_by, v.submitted_at = "pending_approval", svc.payload_hash(shifts), ctx.user_id, datetime.now(timezone.utc)
    svc.event(db, ctx, v, "submitted", {"shifts": len(shifts), "payload_hash": v.payload_hash})
    return svc.serialise(v)


class Decision(BaseModel):
    note: str = Field(default="", max_length=500)


@router.post("/rosters/{version_id}/approve")
def approve(version_id: str, body: Decision, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    svc.require(ctx, "labour.approve")
    v = svc.get_version(db, ctx, version_id)
    if v.state != "pending_approval":
        raise PolicyConflict(f"only a submitted roster can be approved (this is {v.state})")
    if v.submitted_by == ctx.user_id:
        from app.errors import AuthForbidden
        raise AuthForbidden("the submitter cannot approve their own roster (segregation of duties)")
    shifts = svc.version_shifts(db, v)
    if svc.payload_hash(shifts) != v.payload_hash:
        svc.invalidate_if_needed(db, ctx, v)
        raise PolicyConflict("the roster changed after it was submitted; approval invalidated")
    if svc.board(db, ctx, _site(db, ctx, v.site_id), v)["hard_conflicts"]:
        raise PolicyConflict("hard conflicts exist; the roster cannot be approved")
    v.state, v.approved_by, v.approved_at, v.decision_note = "approved", ctx.user_id, datetime.now(timezone.utc), body.note
    svc.event(db, ctx, v, "approved", {"note": body.note, "payload_hash": v.payload_hash})
    return svc.serialise(v)


class Rejection(BaseModel):
    note: str = Field(min_length=3, max_length=500)


@router.post("/rosters/{version_id}/reject")
def reject(version_id: str, body: Rejection, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    svc.require(ctx, "labour.approve")
    v = svc.get_version(db, ctx, version_id)
    if v.state not in ("pending_approval", "approved"):
        raise PolicyConflict(f"nothing to reject (this is {v.state})")
    v.state, v.decision_note = "rejected", body.note
    svc.event(db, ctx, v, "rejected", {"note": body.note})
    return svc.serialise(v)


@router.post("/rosters/{version_id}/publish")
def publish(version_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db),
            idempotency_key: str | None = Header(default=None)) -> dict:
    """Validate → approval → execute → reconcile, natively. Idempotent: re-publishing a published version is a no-op."""
    svc.require(ctx, "labour.approve")
    if not idempotency_key:
        raise ScopeError("Idempotency-Key header is required for this operation")
    v = svc.get_version(db, ctx, version_id)
    if v.state in ("published", "reconciled"):
        return {**svc.serialise(v), "idempotent_replay": True}
    if v.state != "approved":
        raise PolicyConflict(f"only an approved roster can be published (this is {v.state})")
    site = _site(db, ctx, v.site_id)
    shifts = svc.version_shifts(db, v)
    if svc.payload_hash(shifts) != v.payload_hash:
        svc.invalidate_if_needed(db, ctx, v)
        raise PolicyConflict("the roster changed after approval; approval invalidated — re-submit")
    if svc.board(db, ctx, site, v)["hard_conflicts"]:
        raise PolicyConflict("hard conflicts exist; the roster cannot be published")
    v.state = "publishing"
    svc.event(db, ctx, v, "publishing", {"idempotency_key": idempotency_key})
    ws, we = svc.window(site, v.week_start, v.days)
    workers = [w.worker_id for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.home_site == v.site_id))]
    superseded = 0
    for old in db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == ctx.tenant_id, ShiftAssignment.worker_id.in_(workers or [""]),
                                                        ShiftAssignment.status == "committed", ShiftAssignment.start_at >= ws - timedelta(hours=12), ShiftAssignment.start_at < we)):
        if old.source_ref != v.id:
            old.status = "superseded"
            superseded += 1
    for prev in db.scalars(select(RosterVersion).where(RosterVersion.tenant_id == ctx.tenant_id, RosterVersion.site_id == v.site_id, RosterVersion.week_start == v.week_start,
                                                       RosterVersion.state.in_(("published", "reconciled")), RosterVersion.id != v.id)):
        prev.state = "superseded"
        svc.event(db, ctx, prev, "superseded", {"by": v.id})
    promoted = 0
    for s in shifts:
        if s.status == "proposed":
            s.status = "committed"
            promoted += 1
    db.flush()
    v.published_at, v.published_by, v.state = datetime.now(timezone.utc), ctx.user_id, "published"
    svc.event(db, ctx, v, "published", {"promoted": promoted, "superseded_previous_rows": superseded})
    out = _reconcile(db, ctx, v, site)
    from app.api.v1 import handoffs
    handoffs.create_for_version(db, ctx, v, site)
    return out


def _reconcile(db: Session, ctx: RequestContext, v: RosterVersion, site) -> dict:
    committed = list(db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == ctx.tenant_id, ShiftAssignment.source_ref == v.id, ShiftAssignment.status == "committed")))
    all_rows = svc.version_shifts(db, v)
    keys = [(s.worker_id, svc._aware(s.start_at)) for s in committed]
    ws, we = svc.window(site, v.week_start, v.days)
    workers = [w.worker_id for w in db.scalars(select(Worker).where(Worker.tenant_id == ctx.tenant_id, Worker.home_site == v.site_id))]
    foreign = db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == ctx.tenant_id, ShiftAssignment.worker_id.in_(workers or [""]), ShiftAssignment.status == "committed",
                                                       ShiftAssignment.start_at >= ws, ShiftAssignment.start_at < we, ShiftAssignment.source_ref != v.id)).all()
    checks = {"committed_equals_version": len(committed) == len(all_rows), "no_duplicate_assignments": len(keys) == len(set(keys)),
              "hash_matches_approval": svc.payload_hash(committed) == v.payload_hash, "no_other_live_rows_in_window": len(foreign) == 0}
    v.reconciliation = {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks, "committed": len(committed), "version_rows": len(all_rows)}
    v.state = "reconciled" if all(checks.values()) else "unknown"
    svc.event(db, ctx, v, "reconciled" if v.state == "reconciled" else "reconciliation_failed", v.reconciliation)
    return svc.serialise(v)


@router.post("/rosters/{version_id}/reconcile")
def reconcile(version_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    svc.require(ctx, "labour.approve")
    v = svc.get_version(db, ctx, version_id)
    if v.state not in ("published", "unknown", "reconciled"):
        raise PolicyConflict(f"nothing to reconcile (this is {v.state})")
    return _reconcile(db, ctx, v, _site(db, ctx, v.site_id))
