"""Platform administration — a separate principal and route space (blueprint §3.4, §5.2).

A platform admin manages tenant lifecycle, platform admins and support grants. There is no
route here (or anywhere) that returns tenant business data to a platform principal: reaching a
tenant needs a live, time-boxed, reasoned support grant, and even then only impersonation-free
diagnostics. Every action needs MFA; sensitive ones need a fresh step-up. All are audited.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import auth
from app.dependencies import get_db, get_platform_principal
from app.errors import AuthForbidden, RunNotFound, ScopeError
from app.models.identity import (
    PlatformAdmin, PrivilegedSupportGrant, SecurityAuditEvent, TempoUser, Tenant, TenantMembership,
    UserRoleAssignment, UserSiteGrant,
)

from app.api.v1.platform_billing import SubscriptionIn, apply_subscription  # noqa: E402

router = APIRouter(prefix="/platform", tags=["platform"])
MAX_SUPPORT_GRANT = timedelta(hours=8)
_SLUG = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def _cid(request: Request) -> str:
    return getattr(request.state, "correlation_id", "n/a")


def _invite(db: Session, *, email: str | None, subject: str | None) -> TempoUser:
    """Resolve or create the user for an explicit verified subject, or a pending email invitation
    that links only when that address is verified by the IdP at first login."""
    if bool(email) == bool(subject):
        raise ScopeError("provide exactly one of email or subject")
    if subject:
        user = db.scalar(select(TempoUser).where(TempoUser.external_subject == subject))
        if user is None:
            user = TempoUser(external_subject=subject)
            db.add(user)
    else:
        email = email.strip().lower()
        user = db.scalar(select(TempoUser).where(TempoUser.email == email)) or db.scalar(
            select(TempoUser).where(TempoUser.external_subject == f"pending:email:{email}"))
        if user is None:
            user = TempoUser(external_subject=f"pending:email:{email}", email=email)
            db.add(user)
    db.flush()
    return user


class Identity(BaseModel):
    email: str | None = None
    subject: str | None = None


class TenantCreate(BaseModel):
    tenant_id: str
    name: str = Field(min_length=2, max_length=120)
    first_admin: Identity
    initial_site_ids: list[str] = Field(min_length=1, max_length=50)
    subscription: "SubscriptionIn | None" = None   # a manual plan/entitlement recorded at creation (no Stripe checkout needed)


@router.get("/tenants")
def list_tenants(p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> list[dict]:
    return [{"tenant_id": t.tenant_id, "name": t.name, "status": t.status, "plan": t.plan, "writeback_enabled": t.writeback_enabled,
             "created_at": t.created_at.isoformat()} for t in db.scalars(select(Tenant).order_by(Tenant.created_at))]


@router.post("/tenants", status_code=201)
def create_tenant(body: TenantCreate, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal),
                  db: Session = Depends(get_db)) -> dict:
    auth.require_step_up(p)
    if not _SLUG.match(body.tenant_id):
        raise ScopeError("tenant_id must be lower-case letters, digits or underscores")
    if db.get(Tenant, body.tenant_id) is not None:
        raise ScopeError("tenant already exists")
    if body.subscription is not None and body.subscription.licensed_sites < len(set(body.initial_site_ids)):
        raise ScopeError("licensed_sites cannot be fewer than the initial sites")
    db.add(Tenant(tenant_id=body.tenant_id, name=body.name, created_by=p.user_id))
    db.flush()
    from app.db import bind_tenant  # writes to tenant-owned tables need the tenant context
    admin = _invite(db, email=body.first_admin.email, subject=body.first_admin.subject)
    bind_tenant(db, body.tenant_id)
    db.add(TenantMembership(user_id=admin.user_id, tenant_id=body.tenant_id, is_default=True, invitation_source=f"platform:{p.user_id}"))
    db.add(UserRoleAssignment(user_id=admin.user_id, tenant_id=body.tenant_id, role="tenant_admin"))
    for site in sorted(set(body.initial_site_ids)):
        db.add(UserSiteGrant(user_id=admin.user_id, tenant_id=body.tenant_id, site_id=site))
    if body.subscription is not None:
        apply_subscription(db, body.tenant_id, body.subscription, p.user_id)
        bind_tenant(db, body.tenant_id)
    db.flush()
    from app.db import begin_auth_lookup
    begin_auth_lookup(db)
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, tenant_id=body.tenant_id, action="platform.tenant_create",
               decision="allowed", correlation_id=_cid(request))
    from app.core import password_login as pl
    from app.db import begin_auth_lookup as _b
    _b(db)
    token = pl.create_invitation(db, admin, p.user_id) if admin.password_hash is None else None
    return {"tenant_id": body.tenant_id, "first_admin_user_id": admin.user_id, "status": "active", "invite_token": token,
            "invite_path": f"/invite?token={token}" if token else None}


class TenantAdminInvite(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)


@router.post("/tenants/{tenant_id}/admins", status_code=201)
def invite_tenant_admin(tenant_id: str, body: TenantAdminInvite, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> dict:
    """Invite another administrator into an existing organisation (or re-issue the link for one who has not set a password yet).
    They receive the same sites the organisation's existing administrators have. The invitation link is shown once; Tempo does not email it."""
    auth.require_step_up(p)
    t = db.get(Tenant, tenant_id)
    if t is None:
        raise RunNotFound("tenant not found")
    from app.core import password_login as pl
    from app.db import begin_auth_lookup, bind_tenant
    admin = _invite(db, email=body.email, subject=None)
    bind_tenant(db, tenant_id)
    existing = db.get(TenantMembership, (admin.user_id, tenant_id))
    if existing is None:
        db.add(TenantMembership(user_id=admin.user_id, tenant_id=tenant_id, is_default=False, invitation_source=f"platform:{p.user_id}"))
    admins = list(db.scalars(select(UserRoleAssignment.user_id).where(UserRoleAssignment.tenant_id == tenant_id, UserRoleAssignment.role == "tenant_admin")))
    sites = sorted(set(db.scalars(select(UserSiteGrant.site_id).where(UserSiteGrant.tenant_id == tenant_id, UserSiteGrant.user_id.in_(admins or [""])))))
    if not db.scalar(select(UserRoleAssignment.id).where(UserRoleAssignment.user_id == admin.user_id, UserRoleAssignment.tenant_id == tenant_id, UserRoleAssignment.role == "tenant_admin")):
        db.add(UserRoleAssignment(user_id=admin.user_id, tenant_id=tenant_id, role="tenant_admin"))
    have = set(db.scalars(select(UserSiteGrant.site_id).where(UserSiteGrant.user_id == admin.user_id, UserSiteGrant.tenant_id == tenant_id)))
    for sid in sites:
        if sid not in have:
            db.add(UserSiteGrant(user_id=admin.user_id, tenant_id=tenant_id, site_id=sid))
    db.flush()
    begin_auth_lookup(db)
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, tenant_id=tenant_id, action="platform.tenant_admin_invite", decision="allowed", reason_code="reissued" if existing else "created", session_ref=admin.user_id, correlation_id=_cid(request))
    token = pl.create_invitation(db, admin, p.user_id, purpose="reset" if admin.password_hash else "invite")
    return {"tenant_id": tenant_id, "user_id": admin.user_id, "invite_token": token, "invite_path": f"/invite?token={token}", "sites": sites}


@router.post("/tenants/{tenant_id}/status")
def set_tenant_status(tenant_id: str, status: str, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal),
                      db: Session = Depends(get_db)) -> dict:
    auth.require_step_up(p)
    if status not in ("active", "suspended"):
        raise ScopeError("status must be active or suspended")
    t = db.get(Tenant, tenant_id)
    if t is None:
        raise RunNotFound("tenant not found")
    t.status = status
    from app.core import subscription as _sub
    from app.db import begin_auth_lookup as _bal, bind_tenant as _bt
    _bt(db, tenant_id)
    if db.get(_sub.TenantSubscription, tenant_id) is not None:
        _sub.event(db, tenant_id, p.user_id, f"tenant_{status}", "", {})
    _bal(db)
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, tenant_id=tenant_id, action=f"platform.tenant_{status}",
               decision="allowed", correlation_id=_cid(request))
    return {"tenant_id": tenant_id, "status": status}


@router.post("/tenants/{tenant_id}/writeback")
def set_tenant_writeback(tenant_id: str, enabled: bool, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal),
                         db: Session = Depends(get_db)) -> dict:
    """Tenant-level publication kill switch (default OFF; turning it on is a deliberate, audited act)."""
    auth.require_step_up(p)
    t = db.get(Tenant, tenant_id)
    if t is None:
        raise RunNotFound("tenant not found")
    t.writeback_enabled = enabled
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, tenant_id=tenant_id, action="platform.writeback_switch",
               decision="allowed", reason_code="on" if enabled else "off", correlation_id=_cid(request))
    return {"tenant_id": tenant_id, "writeback_enabled": enabled}


@router.post("/admins", status_code=201)
def add_platform_admin(body: Identity, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal),
                       db: Session = Depends(get_db)) -> dict:
    """Second-admin recovery/creation: only an existing, MFA-stepped-up platform admin can add another."""
    auth.require_step_up(p)
    user = _invite(db, email=body.email, subject=body.subject)
    if db.get(PlatformAdmin, user.user_id) is None:
        db.add(PlatformAdmin(user_id=user.user_id, created_by=p.user_id))
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, action="platform.admin_add", decision="allowed",
               session_ref=user.user_id, correlation_id=_cid(request))
    from app.core import password_login as pl
    token = pl.create_invitation(db, user, p.user_id) if user.password_hash is None else None
    return {"user_id": user.user_id, "invite_token": token, "invite_path": f"/invite?token={token}" if token else None}


class SupportGrantCreate(BaseModel):
    target_tenant_id: str
    reason: str = Field(min_length=10, max_length=500)
    hours: float = Field(gt=0, le=8)
    action_categories: list[str] = Field(min_length=1)
    site_ids: list[str] = Field(min_length=1)
    approver_user_id: str | None = None


@router.post("/support-grants", status_code=201)
def create_support_grant(body: SupportGrantCreate, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal),
                         db: Session = Depends(get_db)) -> dict:
    auth.require_step_up(p)
    if db.get(Tenant, body.target_tenant_id) is None:
        raise RunNotFound("tenant not found")
    admins = db.scalar(select(func.count()).select_from(PlatformAdmin).where(PlatformAdmin.revoked_at.is_(None))) or 0
    approver = body.approver_user_id or p.user_id
    sole = admins <= 1
    if approver == p.user_id and not sole:
        raise AuthForbidden("a distinct platform admin must approve a support grant")
    pa = db.get(PlatformAdmin, approver)
    if pa is None or pa.revoked_at is not None:
        raise ScopeError("approver is not an active platform admin")
    now = datetime.now(timezone.utc)
    g = PrivilegedSupportGrant(operator_user_id=p.user_id, login_session_id=p.session_id, target_tenant_id=body.target_tenant_id,
                               site_ids=body.site_ids, action_categories=body.action_categories, reason=body.reason,
                               approver_user_id=approver, approved_at=now, expires_at=now + min(timedelta(hours=body.hours), MAX_SUPPORT_GRANT))
    db.add(g)
    db.flush()
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, tenant_id=body.target_tenant_id, action="support.grant_create",
               decision="allowed", reason_code="sole_admin_self_approval" if approver == p.user_id else "second_approver",
               session_ref=g.grant_id, correlation_id=_cid(request))
    return {"grant_id": g.grant_id, "expires_at": g.expires_at.isoformat()}


@router.get("/support-grants")
def list_support_grants(p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> list[dict]:
    now = datetime.now(timezone.utc)
    out = []
    for g in db.scalars(select(PrivilegedSupportGrant).order_by(PrivilegedSupportGrant.approved_at.desc()).limit(100)):
        live = g.terminated_at is None and g.expires_at.astimezone(timezone.utc) > now
        out.append({"grant_id": g.grant_id, "operator_user_id": g.operator_user_id, "target_tenant_id": g.target_tenant_id, "reason": g.reason, "site_ids": g.site_ids,
                    "action_categories": g.action_categories, "approver_user_id": g.approver_user_id, "approved_at": g.approved_at, "expires_at": g.expires_at,
                    "terminated_at": g.terminated_at, "state": "live" if live else ("terminated" if g.terminated_at else "expired")})
    return out


@router.post("/support-grants/{grant_id}/terminate")
def terminate_support_grant(grant_id: str, request: Request, p: auth.ResolvedPrincipal = Depends(get_platform_principal),
                            db: Session = Depends(get_db)) -> dict:
    g = db.get(PrivilegedSupportGrant, grant_id)
    if g is None:
        raise RunNotFound("grant not found")
    g.terminated_at = datetime.now(timezone.utc)
    auth.audit(db, actor_type="platform_admin", actor_id=p.user_id, tenant_id=g.target_tenant_id, action="support.grant_terminate",
               decision="allowed", session_ref=g.grant_id, correlation_id=_cid(request))
    return {"grant_id": grant_id, "terminated": True}


@router.get("/audit")
def global_audit(limit: int = 100, p: auth.ResolvedPrincipal = Depends(get_platform_principal), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.scalars(select(SecurityAuditEvent).order_by(SecurityAuditEvent.created_at.desc()).limit(min(limit, 500))).all()
    return [{"event_id": r.event_id, "at": r.created_at.isoformat(), "actor_type": r.actor_type, "actor_id": r.actor_id,
             "tenant_id": r.tenant_id, "action": r.action, "decision": r.decision, "reason_code": r.reason_code} for r in rows]
