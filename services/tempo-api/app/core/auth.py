"""Trusted principal and session boundary (Gate 1, blueprint §5.1).

Identity comes from exactly one place: a Tempo-issued, signed access token
that references a server-side `UserSession` row. Roles and grants are read
from Tempo-owned tables on every request; nothing the caller sends
(headers, body, cookies other than the opaque token) is authority.

* Access token: HS256 JWT, short-lived (default 15 min), `iss=tempo`,
  `aud=tempo-api`, carries only sub/sid/tv/jti — never roles or grants.
* Refresh credential: `<session_id>.<secret>`; only a digest is stored. Each
  use rotates it; presenting an already-rotated refresh token revokes the
  whole session family (replay detection).
* Revocation: session revoke, family revoke, or bumping
  `TempoUser.token_version` invalidates outstanding access tokens at once.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import begin_auth_lookup
from app.errors import AuthForbidden, AuthInvalid
from app.models.identity import (
    PlatformAdmin,
    Tenant,
    SecurityAuditEvent,
    TempoUser,
    TenantMembership,
    UserCustomerGrant,
    UserProviderGrant,
    UserRoleAssignment,
    UserSession,
    UserSiteGrant,
)

ISSUER = "tempo"
AUDIENCE = "tempo-api"
# Roles whose holders must have completed MFA (blueprint §5.1: all admins).
MFA_REQUIRED_ROLES = frozenset({"tenant_admin"})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _signing_key() -> str:
    key = settings.session_signing_key
    if not key:
        if settings.env in ("local", "test"):
            # Deterministic-per-process ephemeral key so a bare local start works
            # without ever shipping a usable default secret.
            return _EPHEMERAL_KEY
        raise RuntimeError("TEMPO_SESSION_SIGNING_KEY is required")
    return key


_EPHEMERAL_KEY = secrets.token_urlsafe(48)


def audit(db: Session, *, actor_type: str, actor_id: str, action: str, decision: str,
          tenant_id: str | None = None, reason_code: str | None = None,
          session_ref: str | None = None, correlation_id: str = "n/a") -> None:
    db.add(SecurityAuditEvent(
        actor_type=actor_type, actor_id=actor_id, tenant_id=tenant_id, action=action,
        decision=decision, reason_code=reason_code, session_or_grant_ref=session_ref,
        correlation_id=correlation_id,
    ))


@dataclass
class IssuedSession:
    session_id: str
    access_token: str
    refresh_token: str
    csrf_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


def _issue_access(user: TempoUser, session_id: str) -> tuple[str, datetime]:
    exp = _now() + timedelta(seconds=settings.access_token_ttl_seconds)
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": user.user_id, "sid": session_id,
         "tv": user.token_version, "jti": uuid.uuid4().hex, "iat": int(_now().timestamp()),
         "exp": int(exp.timestamp())},
        _signing_key(), algorithm="HS256",
    )
    return token, exp


def create_session(db: Session, user: TempoUser, *, mfa: bool, auth_method: str,
                   family_id: str | None = None, device_metadata: dict | None = None) -> IssuedSession:
    begin_auth_lookup(db)
    session_id = str(uuid.uuid4())
    secret = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    refresh_exp = _now() + timedelta(seconds=settings.refresh_token_ttl_seconds)
    db.add(UserSession(
        session_id=session_id, session_family_id=family_id or str(uuid.uuid4()), user_id=user.user_id,
        refresh_token_digest=digest(secret), csrf_digest=digest(csrf), expires_at=refresh_exp,
        device_metadata=device_metadata or {}, mfa_verified_at=_now() if mfa else None,
        auth_method=auth_method,
    ))
    db.flush()
    access, access_exp = _issue_access(user, session_id)
    return IssuedSession(session_id, access, f"{session_id}.{secret}", csrf, access_exp, refresh_exp)


def rotate_refresh(db: Session, refresh_token: str, *, correlation_id: str = "n/a") -> IssuedSession:
    begin_auth_lookup(db)
    try:
        session_id, secret = refresh_token.split(".", 1)
    except ValueError:
        raise AuthInvalid("invalid refresh credential") from None
    row = db.get(UserSession, session_id)
    if row is None or not hmac.compare_digest(row.refresh_token_digest, digest(secret)):
        raise AuthInvalid("invalid refresh credential")
    if row.replaced_by is not None or row.revoked_at is not None:
        # Replay of a rotated/revoked credential: burn the entire family.
        revoke_family(db, row.session_family_id, reason="refresh_replay", correlation_id=correlation_id)
        db.commit()
        raise AuthInvalid("refresh credential no longer valid")
    if _aware(row.expires_at) <= _now():
        raise AuthInvalid("session expired")
    user = db.get(TempoUser, row.user_id)
    if user is None or user.account_status != "active":
        raise AuthInvalid("account not active")
    new = create_session(db, user, mfa=row.mfa_verified_at is not None, auth_method=row.auth_method,
                         family_id=row.session_family_id, device_metadata=row.device_metadata)
    new_row = db.get(UserSession, new.session_id)
    new_row.mfa_verified_at = row.mfa_verified_at
    row.replaced_by = new.session_id
    row.revoked_at = _now()
    return new


def revoke_family(db: Session, family_id: str, *, reason: str, correlation_id: str = "n/a") -> None:
    begin_auth_lookup(db)
    rows = db.scalars(select(UserSession).where(UserSession.session_family_id == family_id)).all()
    for r in rows:
        if r.revoked_at is None:
            r.revoked_at = _now()
    if rows:
        audit(db, actor_type="user", actor_id=rows[0].user_id, action="session.family_revoked",
              decision="applied", reason_code=reason, correlation_id=correlation_id)


def revoke_user_everywhere(db: Session, user_id: str, *, reason: str, correlation_id: str = "n/a") -> None:
    """Bump token_version (kills every outstanding access token) and revoke sessions."""
    begin_auth_lookup(db)
    user = db.get(TempoUser, user_id)
    if user is not None:
        user.token_version += 1
    for r in db.scalars(select(UserSession).where(UserSession.user_id == user_id)):
        if r.revoked_at is None:
            r.revoked_at = _now()
    audit(db, actor_type="user", actor_id=user_id, action="user.sessions_revoked", decision="applied",
          reason_code=reason, correlation_id=correlation_id)


@dataclass(frozen=True)
class ResolvedPrincipal:
    principal_type: str
    user_id: str
    session_id: str
    tenant_id: str | None
    roles: list[str] = field(default_factory=list)
    site_ids: list[str] = field(default_factory=list)
    customer_ids: list[str] = field(default_factory=list)
    provider_ids: list[str] = field(default_factory=list)
    mfa_verified_at: datetime | None = None
    is_platform_admin: bool = False
    csrf_digest: str = ""


def verify_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, _signing_key(), algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
                          options={"require": ["exp", "sub", "sid", "tv", "iss", "aud"]})
    except jwt.PyJWTError:
        raise AuthInvalid("invalid or expired token") from None


def load_session_and_user(db: Session, claims: dict) -> tuple[UserSession, TempoUser]:
    """Server-side revocation check: the JWT alone is never sufficient."""
    begin_auth_lookup(db)
    session = db.get(UserSession, claims["sid"])
    user = db.get(TempoUser, claims["sub"])
    if (session is None or user is None or session.user_id != user.user_id or session.revoked_at is not None
            or _aware(session.expires_at) <= _now() or user.account_status != "active"
            or user.token_version != claims["tv"]):
        raise AuthInvalid("session is not valid")
    return session, user


STEP_UP_WINDOW = timedelta(minutes=30)


def resolve_platform_principal(db: Session, token: str) -> ResolvedPrincipal:
    """Platform routes: requires an active PlatformAdmin row and MFA. Grants no tenant data access."""
    claims = verify_access_token(token)
    session, user = load_session_and_user(db, claims)
    pa = db.get(PlatformAdmin, user.user_id)
    if pa is None or pa.revoked_at is not None:
        raise AuthForbidden("access denied")
    if session.mfa_verified_at is None:
        raise AuthForbidden("multi-factor authentication required")
    return ResolvedPrincipal("platform_admin", user.user_id, session.session_id, None, mfa_verified_at=session.mfa_verified_at,
                             is_platform_admin=True, csrf_digest=session.csrf_digest)


def require_step_up(principal: ResolvedPrincipal) -> None:
    """Sensitive platform actions need a recent MFA assertion (ADR-0008)."""
    at = _aware(principal.mfa_verified_at)
    if at is None or _now() - at > STEP_UP_WINDOW:
        raise AuthForbidden("step-up authentication required")


def resolve_principal(db: Session, token: str, tenant_selector: str | None) -> ResolvedPrincipal:
    claims = verify_access_token(token)
    session, user = load_session_and_user(db, claims)
    is_platform = db.get(PlatformAdmin, user.user_id) is not None and db.get(PlatformAdmin, user.user_id).revoked_at is None
    now = _now()
    memberships = [m for m in db.scalars(select(TenantMembership).where(
        TenantMembership.user_id == user.user_id, TenantMembership.status == "active"))
        if _aware(m.effective_from) <= now and (m.effective_to is None or _aware(m.effective_to) > now)]
    if tenant_selector is None:
        if len(memberships) == 1:
            tenant_selector = memberships[0].tenant_id
        elif not memberships:
            return ResolvedPrincipal("platform_admin" if is_platform else "tenant_user", user.user_id,
                                     session.session_id, None, mfa_verified_at=session.mfa_verified_at,
                                     is_platform_admin=is_platform, csrf_digest=session.csrf_digest)
        else:
            default = [m for m in memberships if m.is_default]
            if not default:
                raise AuthForbidden("tenant selection required")
            tenant_selector = default[0].tenant_id
    # The selector is only ever checked against the caller's own memberships.
    if tenant_selector not in {m.tenant_id for m in memberships}:
        raise AuthForbidden("access denied")
    tid = tenant_selector
    tenant = db.get(Tenant, tid)
    if tenant is None or tenant.status != "active":
        raise AuthForbidden("access denied")
    roles = list(db.scalars(select(UserRoleAssignment.role).where(
        UserRoleAssignment.user_id == user.user_id, UserRoleAssignment.tenant_id == tid)))
    sites = list(db.scalars(select(UserSiteGrant.site_id).where(
        UserSiteGrant.user_id == user.user_id, UserSiteGrant.tenant_id == tid)))
    custs = list(db.scalars(select(UserCustomerGrant.customer_id).where(
        UserCustomerGrant.user_id == user.user_id, UserCustomerGrant.tenant_id == tid)))
    provs = list(db.scalars(select(UserProviderGrant.provider_id).where(
        UserProviderGrant.user_id == user.user_id, UserProviderGrant.tenant_id == tid)))
    from app.core.permissions import ROLE_PRINCIPAL_TYPE
    ptype = "labour_provider_user" if any(ROLE_PRINCIPAL_TYPE.get(r) == "labour_provider_user" for r in roles) else "tenant_user"
    if session.mfa_verified_at is None:
        # Admins without MFA are treated as unprivileged (fail closed).
        roles = [r for r in roles if r not in MFA_REQUIRED_ROLES]
    return ResolvedPrincipal(ptype, user.user_id, session.session_id, tid, roles, sites, custs, provs,
                             session.mfa_verified_at, is_platform, session.csrf_digest)
