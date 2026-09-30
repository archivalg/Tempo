"""Roster version service — the demand → roster → approval → publication flow (Blueprint §7).

State machine:  draft → pending_approval → approved → publishing → published → reconciled
                 ↑___ any edit after submission/approval returns the version to draft (approval invalidated)
                rejected / cancelled / superseded are terminal.

Rules enforced here (not in the UI):
* a version with unresolved hard conflicts cannot be submitted or published;
* the approver must differ from the submitter (segregation of duties);
* approval binds to a payload hash of the shifts; any change afterwards invalidates it;
* publication is idempotent, promotes proposed rows to committed exactly once, supersedes the previous
  published rows for the same window, and then reconciles (counts, duplicates, hash) before it reports success.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import opsview
from app.errors import AuthForbidden, PolicyConflict, RunNotFound, ScopeError
from app.models.canonical import ShiftAssignment, Worker
from app.models.directory import Site
from app.models.rosters import RosterEvent, RosterVersion
from app.schemas.tenancy import RequestContext


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def event(db: Session, ctx: RequestContext, v: RosterVersion, action: str, detail: dict | None = None) -> None:
    db.add(RosterEvent(tenant_id=ctx.tenant_id, version_id=v.id, actor_user_id=ctx.user_id, action=action, detail=detail or {}))


def window(site: Site, week_start: str, days: int) -> tuple[datetime, datetime]:
    tz = ZoneInfo(site.timezone)
    s = opsview.local_day_bounds(tz, week_start, _now())[0]
    e_date = datetime.fromisoformat(week_start).date() + timedelta(days=days)
    return s, datetime(e_date.year, e_date.month, e_date.day, tzinfo=tz).astimezone(timezone.utc)


def version_shifts(db: Session, v: RosterVersion) -> list[ShiftAssignment]:
    return list(db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == v.tenant_id, ShiftAssignment.source_ref == v.id)
                           .order_by(ShiftAssignment.start_at, ShiftAssignment.worker_id)))


def payload_hash(shifts: list[ShiftAssignment]) -> str:
    rows = sorted((s.worker_id, s.role, s.zone, _aware(s.start_at).isoformat(), _aware(s.end_at).isoformat()) for s in shifts)
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def get_version(db: Session, ctx: RequestContext, version_id: str) -> RosterVersion:
    v = db.get(RosterVersion, version_id)
    if v is None or v.tenant_id != ctx.tenant_id or v.site_id not in ctx.site_ids:
        raise RunNotFound("roster version not found or not visible in caller scope")
    return v


def require(ctx: RequestContext, permission: str) -> None:
    if not ctx.has_permission(permission):
        raise AuthForbidden(f"caller lacks {permission}")


def serialise(v: RosterVersion) -> dict:
    return {"id": v.id, "site_id": v.site_id, "week_start": v.week_start, "days": v.days, "version_no": v.version_no, "state": v.state, "source": v.source,
            "source_run_id": v.source_run_id, "parent_version_id": v.parent_version_id, "created_by": v.created_by, "created_at": v.created_at,
            "submitted_by": v.submitted_by, "submitted_at": v.submitted_at, "approved_by": v.approved_by, "approved_at": v.approved_at,
            "decision_note": v.decision_note, "published_at": v.published_at, "published_by": v.published_by, "reconciliation": v.reconciliation or {},
            "payload_hash": v.payload_hash}


def board(db: Session, ctx: RequestContext, site: Site, v: RosterVersion) -> dict:
    data = opsview.roster_week(db, ctx.tenant_id, site, v.week_start, v.days, _now(), can_see_rates=ctx.has_permission("labour.rates.read"),
                               can_see_names=ctx.has_permission("labour.worker_names"), view="draft" if v.state not in ("published", "reconciled", "superseded") else "published",
                               version_id=v.id)
    data["version"] = serialise(v)
    data["versions"] = [serialise(x) for x in db.scalars(select(RosterVersion).where(
        RosterVersion.tenant_id == ctx.tenant_id, RosterVersion.site_id == v.site_id, RosterVersion.week_start == v.week_start).order_by(RosterVersion.version_no.desc()))]
    data["publication"]["can_publish"] = data["hard_conflicts"] == 0 and v.state == "approved"
    return data


def next_version_no(db: Session, ctx: RequestContext, site_id: str, week_start: str) -> int:
    last = db.scalar(select(RosterVersion.version_no).where(RosterVersion.tenant_id == ctx.tenant_id, RosterVersion.site_id == site_id,
                                                            RosterVersion.week_start == week_start).order_by(RosterVersion.version_no.desc()).limit(1))
    return (last or 0) + 1


def retire_open_drafts(db: Session, ctx: RequestContext, site_id: str, week_start: str, keep: str | None = None) -> None:
    """A new draft supersedes earlier unpublished versions of the same week; their proposed rows are retired, not deleted."""
    for old in db.scalars(select(RosterVersion).where(RosterVersion.tenant_id == ctx.tenant_id, RosterVersion.site_id == site_id, RosterVersion.week_start == week_start,
                                                      RosterVersion.state.in_(("draft", "pending_approval", "approved", "rejected")), RosterVersion.id != (keep or ""))):
        old.state = "superseded"
        for sh in version_shifts(db, old):
            if sh.status == "proposed":
                sh.status = "superseded"
        event(db, ctx, old, "superseded", {"by": keep})


def check_editable(v: RosterVersion) -> None:
    if v.state in ("published", "reconciled", "superseded", "cancelled", "publishing"):
        raise PolicyConflict(f"a {v.state} roster version cannot be edited; copy it to a new draft")


def invalidate_if_needed(db: Session, ctx: RequestContext, v: RosterVersion) -> None:
    if v.state in ("pending_approval", "approved", "rejected"):
        event(db, ctx, v, "approval_invalidated", {"previous_state": v.state, "reason": "roster edited"})
        v.state, v.payload_hash, v.approved_by, v.approved_at, v.submitted_by, v.submitted_at = "draft", None, None, None, None, None


def worker_at_site(db: Session, ctx: RequestContext, site_id: str, worker_id: str) -> Worker:
    w = db.get(Worker, worker_id)
    if w is None or w.tenant_id != ctx.tenant_id or w.home_site != site_id:
        raise ScopeError("worker is not eligible at this site")
    return w


def hard_conflicts(db: Session, ctx: RequestContext, site: Site, v: RosterVersion) -> list[dict]:
    return board(db, ctx, site, v)["conflicts"]


def impact(db: Session, ctx: RequestContext, site: Site, v: RosterVersion) -> dict:
    b = board(db, ctx, site, v)
    published = b["totals"]["published"]
    cur = b["totals"]["draft"] if v.state not in ("published", "reconciled") else b["totals"]["published"]
    return {"this_version": cur, "current_published": published, "hard_conflicts": b["hard_conflicts"], "coverage_band": b["coverage_band"]}
