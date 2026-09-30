"""Login, session refresh/logout and /me/access.

Browser sessions: short-lived access token + rotating refresh credential in
Secure HttpOnly cookies, CSRF token readable by the console (double submit,
verified against a stored digest). The console never stores tokens or roles.
"""
from __future__ import annotations

import secrets

import jwt
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.core import auth
from app.core.access_scope import PrincipalContext, resolve_access_scope
from app.core.login import login_verified_identity
from app.core.oidc import DevIdentityProvider, get_oidc, new_pkce
from app.dependencies import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, get_db, get_principal
from app.errors import AuthInvalid

router = APIRouter(tags=["auth"])
_STATE_COOKIE = "tempo_oidc"


def _set_session_cookies(resp: Response, s: auth.IssuedSession) -> None:
    common = {"secure": settings.session_cookie_secure, "samesite": "lax", "domain": settings.cookie_domain or None}
    resp.set_cookie(ACCESS_COOKIE, s.access_token, httponly=True, max_age=settings.access_token_ttl_seconds, path="/", **common)
    resp.set_cookie(REFRESH_COOKIE, s.refresh_token, httponly=True, max_age=settings.refresh_token_ttl_seconds, path="/v1/auth", **common)
    resp.set_cookie(CSRF_COOKIE, s.csrf_token, httponly=False, max_age=settings.refresh_token_ttl_seconds, path="/", **common)


def _clear(resp: Response) -> None:
    d = settings.cookie_domain or None
    resp.delete_cookie(ACCESS_COOKIE, path="/", domain=d)
    resp.delete_cookie(REFRESH_COOKIE, path="/v1/auth", domain=d)
    resp.delete_cookie(CSRF_COOKIE, path="/", domain=d)


class AuthConfig(BaseModel):
    provider: str
    production_authentication: bool
    notice: str | None = None


@router.get("/auth/config", response_model=AuthConfig)
def auth_config() -> AuthConfig:
    if settings.dev_idp_enabled:
        return AuthConfig(provider="dev-local", production_authentication=False,
                          notice="Local development identity. Not production authentication.")
    return AuthConfig(provider="oidc" if get_oidc() else "unconfigured", production_authentication=bool(get_oidc()))


@router.get("/auth/dev-identities")
def dev_identities(db: Session = Depends(get_db)) -> list[dict]:
    """Local development only: lists the synthetic demo identities so the login screen can offer them.
    Returns 404-equivalent (empty) unless the dev IdP is enabled, and the dev IdP itself refuses to run
    outside TEMPO_ENV=local|test."""
    if not settings.dev_idp_enabled or settings.env not in ("local", "test"):
        raise AuthInvalid("dev identity provider is disabled")
    from sqlalchemy import select
    from app.db import begin_auth_lookup
    from app.models.identity import TempoUser
    begin_auth_lookup(db)
    rows = db.scalars(select(TempoUser).where(TempoUser.email.like("%@demo.tempo.invalid")).order_by(TempoUser.email)).all()
    return [{"subject": u.external_subject, "email": u.email, "display_name": u.display_name} for u in rows]


class DevLogin(BaseModel):
    subject: str
    email: str | None = None
    name: str | None = None
    mfa: bool = False


@router.post("/auth/dev-login")
def dev_login(body: DevLogin, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    ident = DevIdentityProvider().assert_identity(body.subject, body.email, body.name, body.mfa)
    issued = login_verified_identity(db, ident, auth_method="dev-local",
                                     correlation_id=getattr(request.state, "correlation_id", "n/a"))
    _set_session_cookies(response, issued)
    return {"idp": "dev-local", "production_authentication": False, "access_token": issued.access_token,
            "csrf_token": issued.csrf_token, "expires_at": issued.access_expires_at.isoformat()}


@router.get("/auth/login")
def oidc_login(request: Request) -> Response:
    provider = get_oidc()
    if provider is None:
        raise AuthInvalid("OIDC is not configured")
    state, nonce = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    verifier, challenge = new_pkce()
    redirect_uri = str(request.url_for("oidc_callback"))
    packed = jwt.encode({"s": state, "n": nonce, "v": verifier}, auth._signing_key(), algorithm="HS256")
    resp = Response(status_code=302, headers={"Location": provider.authorization_url(state, nonce, challenge, redirect_uri)})
    resp.set_cookie(_STATE_COOKIE, packed, httponly=True, secure=settings.session_cookie_secure, samesite="lax", max_age=600, path="/v1/auth")
    return resp


@router.get("/auth/callback", name="oidc_callback")
def oidc_callback(request: Request, code: str, state: str, db: Session = Depends(get_db)) -> Response:
    provider = get_oidc()
    packed = request.cookies.get(_STATE_COOKIE)
    if provider is None or not packed:
        raise AuthInvalid("login state missing")
    try:
        st = jwt.decode(packed, auth._signing_key(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise AuthInvalid("login state invalid") from None
    if st["s"] != state:
        raise AuthInvalid("login state mismatch")
    ident = provider.exchange(code, st["v"], st["n"], str(request.url_for("oidc_callback")))
    issued = login_verified_identity(db, ident, auth_method="oidc",
                                     correlation_id=getattr(request.state, "correlation_id", "n/a"))
    resp = Response(status_code=302, headers={"Location": "/"})
    _set_session_cookies(resp, issued)
    resp.delete_cookie(_STATE_COOKIE, path="/v1/auth")
    return resp


@router.post("/auth/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise AuthInvalid("no refresh credential")
    csrf = request.headers.get("x-csrf-token", "")
    session_id = token.split(".", 1)[0]
    from app.db import begin_auth_lookup
    from app.models.identity import UserSession
    begin_auth_lookup(db)
    row = db.get(UserSession, session_id)
    if row is None or not csrf or auth.digest(csrf) != row.csrf_digest:
        raise AuthInvalid("csrf validation failed")
    issued = auth.rotate_refresh(db, token, correlation_id=getattr(request.state, "correlation_id", "n/a"))
    _set_session_cookies(response, issued)
    return {"expires_at": issued.access_expires_at.isoformat(), "access_token": issued.access_token}


@router.post("/auth/logout")
def logout(response: Response, principal: auth.ResolvedPrincipal = Depends(get_principal),
           db: Session = Depends(get_db)) -> dict:
    from app.models.identity import UserSession
    row = db.get(UserSession, principal.session_id)
    if row is not None:
        auth.revoke_family(db, row.session_family_id, reason="logout")
    _clear(response)
    return {"status": "signed_out"}


@router.get("/me/access")
def me_access(principal: auth.ResolvedPrincipal = Depends(get_principal)) -> dict:
    """The server's resolved view of the caller: what the UI may show (never authority itself)."""
    base = {"user_id": principal.user_id, "platform_admin": principal.is_platform_admin,
            "mfa_verified": principal.mfa_verified_at is not None, "idp": "dev-local" if settings.dev_idp_enabled else "oidc"}
    if principal.tenant_id is None:
        return {**base, "tenant_id": None, "permissions": [], "site_ids": [], "customer_ids": [], "provider_ids": [], "roles": []}
    scope = resolve_access_scope(PrincipalContext(
        principal_type=principal.principal_type, tenant_id=principal.tenant_id, user_id=principal.user_id,
        roles=principal.roles, site_grants=principal.site_ids, customer_grants=principal.customer_ids,
        provider_grants=principal.provider_ids))
    return {**base, "tenant_id": principal.tenant_id, "roles": sorted(principal.roles),
            "permissions": sorted(scope.permissions), "site_ids": sorted(scope.site_ids),
            "customer_ids": sorted(scope.customer_ids), "provider_ids": sorted(scope.provider_ids)}
