"""Support sessions (roadmap M6-ADMIN): a platform operator with a live, reasoned, time-boxed grant gets READ-ONLY diagnostics for one tenant.

* The grant, not the operator's login, is the authority: it must belong to the caller, be unexpired and unterminated, and carry the 'diagnostics' category.
  Checked on every request, so expiry and revocation take effect at the API, not only in the screen.
* The response is counts, states and health. No worker names, pay, personal data or raw payloads are returned.
* Reads are limited to the grant's sites (row security is bound to them) and every read is audited under the operator's own identity with the grant reference.
* Operational changes, exports and sensitive data are not offered here: they would need their own category and are not built.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import auth, subscription as sub
from app.db import begin_auth_lookup, bind_sites, bind_tenant
from app.dependencies import get_db, get_platform_principal
from app.errors import AuthForbidden, RunNotFound
from app.models.canonical import AttendanceSession, Worker
from app.models.connectors import MaestroConnection
from app.models.directory import ExceptionCase, Site
from app.models.identity import PrivilegedSupportGrant, SecurityAuditEvent, Tenant
from app.models.imports import ImportBatch
from app.models.rosters import RosterVersion

router = APIRouter(prefix="/platform", tags=["support"])


def _live_grant(db: Session, grant_id: str, p: auth.ResolvedPrincipal) -> PrivilegedSupportGrant:
    g = db.get(PrivilegedSupportGrant, grant_id)
    if g is None or g.operator_user_id != p.user_id:
        raise RunNotFound("support grant not found")
    now = datetime.now(timezone.utc)
    if g.terminated_at is not None:
        raise AuthForbidden("this support session was ended")
    if g.expires_at.astimezone(timezone.utc) <= now:
        raise AuthForbidden("this support session has expired")
    if not ({"diagnostics", "diagnose"} & set(g.action_categories or [])):
        raise AuthForbidden("this grant does not include diagnostics")
    return g


def _cid(request: Request) -> str:
    return getattr(request.state, "correlation_id", "n/a")


def _diagnostics(db: Session, g: PrivilegedSupportGrant) -> dict:
    tid = g.target_tenant_id
    t = db.get(Tenant, tid)
    if t is None:
        raise RunNotFound("tenant not found")
    bind_tenant(db, tid)
    bind_sites(db, list(g.site_ids))
    sites = list(db.scalars(select(Site).where(Site.tenant_id == tid).order_by(Site.site_id)))
    site_ids = [s.site_id for s in sites]
    by_state = lambda col, model, **w: {k or "none": n for k, n in db.execute(select(col, func.count()).select_from(model).where(model.tenant_id == tid, *[getattr(model, a) == b for a, b in w.items()]).group_by(col))}  # noqa: E731
    workers = {k: n for k, n in db.execute(select(Worker.status, func.count()).where(Worker.tenant_id == tid, Worker.home_site.in_(site_ids or [""])).group_by(Worker.status))}
    rosters = [{"site_id": r.site_id, "week_start": r.week_start, "version_no": r.version_no, "state": r.state, "source": r.source}
               for r in db.scalars(select(RosterVersion).where(RosterVersion.tenant_id == tid).order_by(RosterVersion.week_start.desc(), RosterVersion.version_no.desc()).limit(12))]
    imports = [{"data_class": b.data_class, "entity": b.entity, "channel": b.channel, "state": b.state, "rows": b.total_rows, "errors": b.error_rows, "at": b.created_at}
               for b in db.scalars(select(ImportBatch).where(ImportBatch.tenant_id == tid).order_by(ImportBatch.created_at.desc()).limit(10))]
    conns = [{"source_system": c.source_system, "site_id": c.site_id, "status": c.status} for c in db.scalars(select(MaestroConnection).where(MaestroConnection.tenant_id == tid, MaestroConnection.site_id.in_(site_ids or [""])))]
    open_exc = {k: n for k, n in db.execute(select(ExceptionCase.kind, func.count()).where(ExceptionCase.tenant_id == tid, ExceptionCase.state.in_(("detected", "triaged", "assigned"))).group_by(ExceptionCase.kind))}
    open_sessions = db.scalar(select(func.count()).select_from(AttendanceSession).where(AttendanceSession.tenant_id == tid, AttendanceSession.state.in_(("working", "on_break")))) or 0
    plan = sub.describe(db, tid)
    plan = {k: v for k, v in plan.items() if k != "history"}
    begin_auth_lookup(db)
    recent = [{"at": e.created_at, "actor_type": e.actor_type, "action": e.action, "decision": e.decision, "reason": e.reason_code}
              for e in db.scalars(select(SecurityAuditEvent).where(SecurityAuditEvent.tenant_id == tid).order_by(SecurityAuditEvent.created_at.desc()).limit(40))]
    return {"tenant": {"tenant_id": tid, "name": t.name, "status": t.status}, "plan": plan, "sites": [{"site_id": s.site_id, "name": s.name, "timezone": s.timezone, "operating_mode": s.operating_mode} for s in sites],
            "workers_by_status": workers, "open_attendance_sessions": open_sessions, "open_exceptions_by_kind": open_exc, "rosters": rosters, "imports": imports, "connections": conns, "recent_security_events": recent,
            "limits": "Read-only counts and states within the granted sites. No names, pay or personal data are shown."}


def _session_info(g: PrivilegedSupportGrant) -> dict:
    return {"grant_id": g.grant_id, "tenant_id": g.target_tenant_id, "reason": g.reason, "site_ids": g.site_ids, "action_categories": g.action_categories, "expires_at": g.expires_at, "mode": "read_only_diagnostics"}


@router.post("/support-grants/{grant_id}/open")
def open_support_session(grant_id: str, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> dict:
    g = _live_grant(db, grant_id, p)
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, tenant_id=g.target_tenant_id, action="support.session_open", decision="allowed", session_ref=g.grant_id, correlation_id=_cid(request))
    return _session_info(g)


@router.get("/support/{grant_id}/diagnostics")
def diagnostics(grant_id: str, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> dict:
    g = _live_grant(db, grant_id, p)
    out = _diagnostics(db, g)
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, tenant_id=g.target_tenant_id, action="support.read", decision="allowed", reason_code="diagnostics", session_ref=g.grant_id, correlation_id=_cid(request))
    return {"session": _session_info(g), **out}
