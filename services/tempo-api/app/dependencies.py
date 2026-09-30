"""Shared FastAPI dependencies: trusted request scope, DB session, idempotency key.

`get_request_context` is the single trust boundary. It never reads identity
from a caller-supplied header: it verifies a Tempo-issued token, loads the
session server-side, derives roles and finite site/customer/provider grants
from Tempo-owned tables (app/core/auth.py), and only then binds the DB
session to the authorised tenant so PostgreSQL RLS applies (app/db.py).
`X-Tempo-Tenant` is a *selector* checked against the caller's own memberships.
"""
from __future__ import annotations

import hmac
from collections.abc import Generator

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core import auth
from app.db import SessionLocal, bind_tenant, begin_auth_lookup
from app.errors import AuthForbidden, AuthInvalid, ScopeError
from app.schemas.tenancy import RequestContext

ACCESS_COOKIE = "tempo_at"
REFRESH_COOKIE = "tempo_rt"
CSRF_COOKIE = "tempo_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _extract_token(request: Request) -> tuple[str, bool]:
    """Returns (token, via_cookie). Bearer takes precedence and is not ambient, so needs no CSRF."""
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip(), False
    cookie = request.cookies.get(ACCESS_COOKIE)
    if cookie:
        return cookie, True
    raise AuthInvalid("authentication required")


def _check_csrf(request: Request, csrf_digest: str) -> None:
    if request.method in SAFE_METHODS:
        return
    sent = request.headers.get("x-csrf-token", "")
    if not sent or not hmac.compare_digest(auth.digest(sent), csrf_digest):
        raise AuthForbidden("csrf validation failed")


def get_principal(
    request: Request,
    db: Session = Depends(get_db),
    x_tempo_tenant: str | None = Header(default=None),
) -> auth.ResolvedPrincipal:
    token, via_cookie = _extract_token(request)
    begin_auth_lookup(db)
    principal = auth.resolve_principal(db, token, x_tempo_tenant)
    if via_cookie:
        _check_csrf(request, principal.csrf_digest)
    request.state.principal = principal
    return principal


def get_request_context(
    request: Request,
    principal: auth.ResolvedPrincipal = Depends(get_principal),
    db: Session = Depends(get_db),
) -> RequestContext:
    if principal.tenant_id is None:
        # e.g. a platform admin with no tenant membership: no tenant-scoped API access.
        raise AuthForbidden("no tenant access")
    if not principal.site_ids and not principal.customer_ids:
        # DP-08 / INT-003: never default to a tenant-wide view.
        raise ScopeError("no site or customer grants: access denied")
    bind_tenant(db, principal.tenant_id)
    return RequestContext(
        tenant_id=principal.tenant_id,
        site_ids=list(principal.site_ids),
        customer_ids=list(principal.customer_ids),
        provider_id=principal.provider_ids[0] if principal.provider_ids else None,
        user_id=principal.user_id,
        roles=list(principal.roles),
        purpose="labour.console",
        correlation_id=getattr(request.state, "correlation_id", "cor_unknown"),
    )


def get_idempotency_key(idempotency_key: str | None = Header(default=None)) -> str | None:
    return idempotency_key


def require_idempotency_key(idempotency_key: str | None = Header(default=None)) -> str:
    if not idempotency_key:
        raise ScopeError("Idempotency-Key header is required for this operation")
    return idempotency_key
