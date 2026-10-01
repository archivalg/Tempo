"""Tenant user administration: invite-only accounts, delegation bounded by the caller's own authority.

* A tenant admin can only grant roles from the catalogue and only sites/customers inside their OWN finite grants.
* Accounts are created without a password; the person sets one through a single-use, expiring invitation link.
* Suspension is per tenant (membership), so it never affects the person's access in another tenant.
* Every change is written to the append-only security audit log.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import auth, password_login as pl
from app.core.permissions import ROLE_PERMISSION_MATRIX
from app.db import auth_phase
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, RunNotFound, ScopeError
from app.models.identity import (
    SecurityAuditEvent, TempoUser, TenantMembership, UserCustomerGrant, UserRoleAssignment, UserSiteGrant,
)
from app.schemas.tenancy import RequestContext

router = APIRouter(prefix="/admin", tags=["admin"])


def _require(ctx: RequestContext) -> None:
    if not ctx.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure required to manage users")


def _check_delegation(ctx: RequestContext, roles: list[str], sites: list[str], customers: list[str]) -> None:
    if "integration_import" in roles:
        raise ScopeError("integration_import is for service credentials only — create an API credential instead of assigning it to a person")
    unknown = [r for r in roles if r not in ROLE_PERMISSION_MATRIX]
    if unknown:
        raise ScopeError(f"unknown role(s): {', '.join(unknown)}")
    if not roles:
        raise ScopeError("choose at least one role")
    if not set(sites) <= set(ctx.site_ids) or not set(customers) <= set(ctx.customer_ids):
        raise ScopeError("you can only grant sites and customers inside your own access")
    if not sites and not customers:
        raise ScopeError("grant at least one site or customer (an empty grant means no access)")


class NewUser(BaseModel):
    email: str = Field(min_length=5, max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str | None = Field(default=None, max_length=120)
    roles: list[str]
    site_ids: list[str] = []
    customer_ids: list[str] = []


class Grants(BaseModel):
    roles: list[str]
    site_ids: list[str] = []
    customer_ids: list[str] = []


def _view(db: Session, ctx: RequestContext, u: TempoUser, m: TenantMembership) -> dict:
    roles = list(db.scalars(select(UserRoleAssignment.role).where(UserRoleAssignment.user_id == u.user_id, UserRoleAssignment.tenant_id == ctx.tenant_id)))
    sites = list(db.scalars(select(UserSiteGrant.site_id).where(UserSiteGrant.user_id == u.user_id, UserSiteGrant.tenant_id == ctx.tenant_id)))
    custs = list(db.scalars(select(UserCustomerGrant.customer_id).where(UserCustomerGrant.user_id == u.user_id, UserCustomerGrant.tenant_id == ctx.tenant_id)))
    return {"user_id": u.user_id, "email": u.email, "username": u.username, "display_name": u.display_name, "roles": sorted(roles), "site_ids": sorted(sites),
            "customer_ids": sorted(custs), "membership": m.status, "has_password": u.password_hash is not None, "mfa_enabled": u.totp_enabled_at is not None,
            "locked": bool(u.locked_until and pl._aware(u.locked_until) > pl._now()), "is_self": u.user_id == ctx.user_id}


def _member(db: Session, ctx: RequestContext, user_id: str) -> tuple[TempoUser, TenantMembership]:
    m = db.get(TenantMembership, (user_id, ctx.tenant_id))
    u = db.get(TempoUser, user_id) if m else None
    if m is None or u is None:
        raise RunNotFound("user not found in this workspace")
    return u, m


@router.get("/users")
def list_users(ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> list[dict]:
    _require(ctx)
    out = []
    for m in db.scalars(select(TenantMembership).where(TenantMembership.tenant_id == ctx.tenant_id)):
        u = db.get(TempoUser, m.user_id)
        if u is not None:
            out.append(_view(db, ctx, u, m))
    return sorted(out, key=lambda r: (r["email"] or "").lower())


def _apply_grants(db: Session, ctx: RequestContext, user_id: str, roles: list[str], sites: list[str], customers: list[str]) -> None:
    for model, col, vals in ((UserRoleAssignment, "role", roles), (UserSiteGrant, "site_id", sites), (UserCustomerGrant, "customer_id", customers)):
        have = {getattr(r, col): r for r in db.scalars(select(model).where(model.user_id == user_id, model.tenant_id == ctx.tenant_id))}
        for v, row in have.items():
            if v not in vals:
                db.delete(row)
        for v in vals:
            if v not in have:
                db.add(model(user_id=user_id, tenant_id=ctx.tenant_id, **{col: v}))
    db.flush()


@router.post("/users", status_code=201)
def invite_user(body: NewUser, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _require(ctx)
    _check_delegation(ctx, body.roles, body.site_ids, body.customer_ids)
    email = body.email.strip().lower()
    with auth_phase(db, ctx.tenant_id):
        u = db.scalar(select(TempoUser).where(TempoUser.email == email))
        if u is None:
            u = TempoUser(external_subject=f"pending:email:{email}", email=email, display_name=body.display_name)
            db.add(u)
            db.flush()
        if db.get(TenantMembership, (u.user_id, ctx.tenant_id)) is not None:
            raise ScopeError("that person already has access to this workspace")
        token = pl.create_invitation(db, u, ctx.user_id) if u.password_hash is None else None
    db.add(TenantMembership(user_id=u.user_id, tenant_id=ctx.tenant_id, is_default=False, invitation_source=f"user:{ctx.user_id}"))
    db.flush()
    _apply_grants(db, ctx, u.user_id, body.roles, body.site_ids, body.customer_ids)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="user.invite", decision="allowed", session_ref=u.user_id,
               reason_code=",".join(sorted(body.roles)), correlation_id=ctx.correlation_id)
    return {**_view(db, ctx, u, db.get(TenantMembership, (u.user_id, ctx.tenant_id))), "invite_token": token,
            "invite_path": f"/invite?token={token}" if token else None,
            "note": "Shown once. Send it to the person over a private channel; it expires and works once." if token else "This person already has an account; the new access applies at their next sign-in."}


@router.put("/users/{user_id}/grants")
def set_grants(user_id: str, body: Grants, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    _require(ctx)
    u, m = _member(db, ctx, user_id)
    if u.user_id == ctx.user_id:
        raise AuthForbidden("you cannot change your own access")
    _check_delegation(ctx, body.roles, body.site_ids, body.customer_ids)
    # never strip a grant this admin cannot see: only sites/customers within the admin's own scope are replaced
    keep_sites = [s for s in db.scalars(select(UserSiteGrant.site_id).where(UserSiteGrant.user_id == user_id, UserSiteGrant.tenant_id == ctx.tenant_id)) if s not in ctx.site_ids]
    keep_custs = [c for c in db.scalars(select(UserCustomerGrant.customer_id).where(UserCustomerGrant.user_id == user_id, UserCustomerGrant.tenant_id == ctx.tenant_id)) if c not in ctx.customer_ids]
    _apply_grants(db, ctx, user_id, body.roles, body.site_ids + keep_sites, body.customer_ids + keep_custs)
    with auth_phase(db, ctx.tenant_id):
        auth.revoke_user_everywhere(db, user_id, reason="grants_changed", correlation_id=ctx.correlation_id)
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="user.grants_set", decision="allowed", session_ref=user_id, correlation_id=ctx.correlation_id)
    return _view(db, ctx, u, m)


def _lifecycle(status: str | None, action: str):
    def handler(user_id: str, ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
        _require(ctx)
        u, m = _member(db, ctx, user_id)
        if u.user_id == ctx.user_id:
            raise AuthForbidden("you cannot do this to your own account")
        out: dict = {}
        if status:
            m.status = status
            if status != "active":
                with auth_phase(db, ctx.tenant_id):
                    auth.revoke_user_everywhere(db, user_id, reason=action, correlation_id=ctx.correlation_id)
        elif action == "user.reset_password":
            with auth_phase(db, ctx.tenant_id):
                out["invite_token"] = pl.create_invitation(db, u, ctx.user_id, purpose="reset")
                out["invite_path"] = f"/invite?token={out['invite_token']}"
                auth.revoke_user_everywhere(db, user_id, reason=action, correlation_id=ctx.correlation_id)
        elif action == "user.reset_mfa":
            with auth_phase(db, ctx.tenant_id):
                u.totp_secret_enc, u.totp_enabled_at, u.totp_last_step = None, None, 0
                auth.revoke_user_everywhere(db, user_id, reason=action, correlation_id=ctx.correlation_id)
        elif action == "user.unlock":
            with auth_phase(db, ctx.tenant_id):
                u.locked_until, u.failed_logins = None, 0
        auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action=action, decision="allowed", session_ref=user_id, correlation_id=ctx.correlation_id)
        return {**_view(db, ctx, u, m), **out}
    return handler


router.post("/users/{user_id}/suspend")(_lifecycle("suspended", "user.suspend"))
router.post("/users/{user_id}/reinstate")(_lifecycle("active", "user.reinstate"))
router.post("/users/{user_id}/reset-password")(_lifecycle(None, "user.reset_password"))
router.post("/users/{user_id}/reset-mfa")(_lifecycle(None, "user.reset_mfa"))
router.post("/users/{user_id}/unlock")(_lifecycle(None, "user.unlock"))


@router.get("/audit")
def audit_log(action: str | None = None, actor: str | None = None, decision: str | None = None, before: datetime | None = None,
              limit: int = Query(default=50, ge=1, le=200), ctx: RequestContext = Depends(get_request_context), db: Session = Depends(get_db)) -> dict:
    """The tenant's own security audit trail (who did what, allowed or denied). Read-only; secrets are never stored in it.
    Newest first; pass the last row's `created_at` as `before` for the next page. Viewing it is itself recorded."""
    _require(ctx)
    q = select(SecurityAuditEvent).where(SecurityAuditEvent.tenant_id == ctx.tenant_id)
    if action:
        q = q.where(SecurityAuditEvent.action.startswith(action))
    if actor:
        q = q.where(SecurityAuditEvent.actor_id == actor)
    if decision:
        q = q.where(SecurityAuditEvent.decision == decision)
    if before:
        q = q.where(SecurityAuditEvent.created_at < before)
    rows = list(db.scalars(q.order_by(SecurityAuditEvent.created_at.desc(), SecurityAuditEvent.event_id).limit(limit + 1)))
    page, more = rows[:limit], len(rows) > limit
    names: dict[str, str] = {}
    ids = {r.actor_id for r in page if r.actor_type == "user"}
    if ids:
        with auth_phase(db, ctx.tenant_id):
            members = set(db.scalars(select(TenantMembership.user_id).where(TenantMembership.tenant_id == ctx.tenant_id, TenantMembership.user_id.in_(ids))))
            for u in db.scalars(select(TempoUser).where(TempoUser.user_id.in_(members or {""}))):
                names[u.user_id] = u.display_name or u.username or u.email or u.user_id
    actions = sorted(set(db.scalars(select(SecurityAuditEvent.action).where(SecurityAuditEvent.tenant_id == ctx.tenant_id).distinct().limit(200))))
    auth.audit(db, actor_type="user", actor_id=ctx.user_id, tenant_id=ctx.tenant_id, action="audit.view", decision="allowed", correlation_id=ctx.correlation_id)
    return {"items": [{"event_id": r.event_id, "at": r.created_at, "actor_type": r.actor_type, "actor_id": r.actor_id, "actor_name": names.get(r.actor_id), "action": r.action,
                       "decision": r.decision, "reason_code": r.reason_code, "ref": r.session_or_grant_ref, "correlation_id": r.correlation_id} for r in page],
            "next_before": page[-1].created_at if more else None, "actions": actions}
