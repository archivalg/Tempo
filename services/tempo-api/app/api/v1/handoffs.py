"""Roster handoff for Overlay sites: take the file, attest it was loaded, or submit through a (gated) vendor connector."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.operations import _site
from app.core import auth, exports, notifications as nt, rosters as svc
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, PolicyConflict, RunNotFound, ScopeError
from app.maestro import roster_handoff as vendor
from app.models.canonical import Worker
from app.models.directory import WorkerPerson
from app.models.identity import Tenant
from app.models.rosters import RosterHandoff, RosterVersion
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["handoffs"])
OPEN = ("pending", "exported", "unconfirmed")


def create_for_version(db: Session, ctx: RequestContext, v: RosterVersion, site) -> RosterHandoff | None:
    """Called when a version is published. Only Overlay sites need a handoff; any older open handoff for the week is superseded."""
    if site.operating_mode != "overlay":
        return None
    for old in db.scalars(select(RosterHandoff).where(RosterHandoff.tenant_id == ctx.tenant_id, RosterHandoff.site_id == v.site_id, RosterHandoff.state.in_(OPEN), RosterHandoff.version_id != v.id)):
        if db.get(RosterVersion, old.version_id).week_start == v.week_start:
            old.state = "superseded"
    shifts = svc.version_shifts(db, v)
    payload = [{"shift_id": s.shift_id, "worker_id": s.worker_id, "role": s.role, "zone": s.zone, "start_at": svc._aware(s.start_at).isoformat(), "end_at": svc._aware(s.end_at).isoformat()} for s in shifts]
    h = RosterHandoff(tenant_id=ctx.tenant_id, site_id=v.site_id, version_id=v.id, payload_hash=v.payload_hash or svc.payload_hash(shifts), payload=payload, created_by=ctx.user_id)
    db.add(h)
    db.flush()
    nt.notify(db, ctx.tenant_id, nt.recipients(db, ctx.tenant_id, v.site_id, "labour.approve", {ctx.user_id}), kind="handoff.pending", severity="action",
              title=f"Published roster needs handing to the external system — week of {v.week_start}", body=f"{len(payload)} shifts. Download the file or submit it.",
              link=f"/roster?start={v.week_start}&v={v.id}", site_id=v.site_id, dedup_key=f"handoff:{h.id}")
    return h


def serialise(h: RosterHandoff) -> dict:
    return {"id": h.id, "site_id": h.site_id, "version_id": h.version_id, "state": h.state, "payload_hash": h.payload_hash, "shifts": len(h.payload or []), "created_at": h.created_at,
            "created_by": h.created_by, "exported_at": h.exported_at, "exported_by": h.exported_by, "file_sha256": h.file_sha256, "submitted_at": h.submitted_at, "submitted_by": h.submitted_by,
            "attempts": h.attempts, "vendor_detail": h.vendor_detail, "confirmed_at": h.confirmed_at, "confirmed_by": h.confirmed_by, "confirm_reference": h.confirm_reference,
            "confirm_note": h.confirm_note,
            "confirmation_kind": "operator_attestation" if h.state == "confirmed_by_operator" else ("vendor" if h.state == "vendor_confirmed" else None)}


def _get(db: Session, ctx: RequestContext, handoff_id: str) -> RosterHandoff:
    h = db.get(RosterHandoff, handoff_id)
    if h is None or h.tenant_id != ctx.tenant_id or h.site_id not in ctx.site_ids:
        raise RunNotFound("handoff not found or not visible in caller scope")
    return h


def _need(ctx: RequestContext, perm: str = "labour.approve") -> None:
    if not ctx.has_permission(perm):
        raise AuthForbidden(f"caller lacks {perm}")


@router.get("/sites/{site_id}/handoffs")
def list_handoffs(site_id: str, version_id: str | None = None, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    site = _site(db, ctx, site_id)
    q = select(RosterHandoff).where(RosterHandoff.tenant_id == ctx.tenant_id, RosterHandoff.site_id == site.site_id)
    if version_id:
        q = q.where(RosterHandoff.version_id == version_id)
    return [serialise(h) for h in db.scalars(q.order_by(RosterHandoff.created_at.desc()).limit(50))]


@router.get("/handoffs/{handoff_id}/file.csv")
def download(handoff_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> Response:
    _need(ctx)
    h = _get(db, ctx, handoff_id)
    if h.state == "superseded":
        raise PolicyConflict("this handoff was superseded by a newer publish — use the latest one")
    site = _site(db, ctx, h.site_id)
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(site.timezone)
    names = {}
    if ctx.has_permission("labour.worker_names"):
        names = {p.worker_id: p.display_name for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == ctx.tenant_id, WorkerPerson.worker_id.in_([x["worker_id"] for x in h.payload] or [""])))}
    loc = lambda iso: datetime.fromisoformat(iso).astimezone(tz).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    rows = [[x["worker_id"], names.get(x["worker_id"], ""), x["role"], x["zone"], loc(x["start_at"]), loc(x["end_at"]), x["start_at"], x["end_at"], x["shift_id"]] for x in sorted(h.payload, key=lambda r: (r["start_at"], r["worker_id"]))]
    body = exports.to_csv(["worker_ref", "worker_name", "role", "zone", "start_local", "end_local", "start_utc", "end_utc", "tempo_shift_id"], rows,
                          [f"Tempo roster handoff — {site.name} ({site.timezone})", f"Roster hash {h.payload_hash}; {len(rows)} shifts. Local times are in the site timezone."])
    digest = hashlib.sha256(body.encode()).hexdigest()
    first = h.exported_at is None
    if h.state == "pending":
        h.state = "exported"
    h.exported_at, h.exported_by, h.file_sha256 = h.exported_at or datetime.now(timezone.utc), h.exported_by or ctx.user_id, digest
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="handoff.export", decision="allowed", reason_code=f"rows={len(rows)}", session_ref=h.id, correlation_id=ctx.correlation_id)
    return Response(body, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="tempo-roster-{h.site_id}-{h.id[-6:]}.csv"', "Cache-Control": "no-store", "X-File-First-Export": str(first).lower()})


class Confirm(BaseModel):
    reference: str = Field(min_length=2, max_length=120)  # e.g. the vendor's import batch / roster id
    note: str = Field(default="", max_length=500)


@router.post("/handoffs/{handoff_id}/confirm")
def confirm(handoff_id: str, body: Confirm, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """A person attests they loaded the file. This is recorded as an operator attestation, never as vendor confirmation."""
    _need(ctx)
    h = _get(db, ctx, handoff_id)
    if h.state != "exported":
        raise PolicyConflict(f"download the file first (this handoff is {h.state})" if h.state == "pending" else f"cannot confirm a handoff that is {h.state}")
    h.state, h.confirmed_at, h.confirmed_by, h.confirm_reference, h.confirm_note = "confirmed_by_operator", datetime.now(timezone.utc), ctx.user_id, body.reference.strip(), body.note
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="handoff.attest", decision="allowed", session_ref=h.id, correlation_id=ctx.correlation_id)
    return serialise(h)


@router.post("/handoffs/{handoff_id}/submit")
def submit(handoff_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db), idempotency_key: str | None = Header(default=None)) -> dict:
    """Send through the vendor connector. Gated by: permission, the tenant's writeback switch (default OFF), a second person
    (not the publisher), and an Idempotency-Key. The outcome is whatever the connector truly returns; `unknown` stays open."""
    _need(ctx)
    if not idempotency_key:
        raise ScopeError("Idempotency-Key header is required for this operation")
    h = _get(db, ctx, handoff_id)
    t = db.get(Tenant, ctx.tenant_id)
    if t is None or not t.writeback_enabled:
        raise PolicyConflict("writeback is switched off for this organisation (platform kill switch) — use the file handoff")
    v = db.get(RosterVersion, h.version_id)
    if v.published_by == ctx.user_id:
        raise AuthForbidden("the person who published the roster cannot also send it to the vendor (segregation of duties)")
    if h.state in ("vendor_confirmed", "confirmed_by_operator"):
        return {**serialise(h), "idempotent_replay": True}
    if h.state not in OPEN + ("rejected",):
        raise PolicyConflict(f"a handoff that is {h.state} cannot be submitted")
    outcome = vendor.vendor_roster_client.submit_roster(h.site_id, h.payload_hash, h.payload, f"{h.id}:{idempotency_key}")
    h.attempts += 1
    h.submitted_at, h.submitted_by, h.vendor_detail = datetime.now(timezone.utc), ctx.user_id, outcome.detail
    h.state = {"confirmed": "vendor_confirmed", "rejected": "rejected"}.get(outcome.status, "unconfirmed")
    if h.state == "vendor_confirmed":
        h.confirmed_at, h.confirmed_by = h.submitted_at, "vendor"
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="handoff.submit", decision="allowed", reason_code=h.state, session_ref=h.id, correlation_id=ctx.correlation_id)
    return serialise(h)
