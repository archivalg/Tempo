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
    methods: list[str] = []


@router.get("/auth/config", response_model=AuthConfig)
def auth_config() -> AuthConfig:
    methods = (["password"] if settings.password_auth_enabled else []) + (["oidc"] if get_oidc() else []) + (["dev-local"] if settings.dev_idp_enabled else [])
    if settings.dev_idp_enabled:
        return AuthConfig(provider="dev-local", production_authentication=False, notice="Local development identity. Not production authentication.", methods=methods)
    primary = "password" if settings.password_auth_enabled else ("oidc" if get_oidc() else "unconfigured")
    return AuthConfig(provider=primary, production_authentication=bool(methods), methods=methods)


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


@router.get("/auth/oidc/login")
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


@router.get("/auth/oidc/callback", name="oidc_callback")
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
def me_access(principal: auth.ResolvedPrincipal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    """The server's resolved view of the caller: what the UI may show (never authority itself)."""
    from app.core import password_login as _pl
    begin_auth_lookup(db)
    u = db.get(TempoUser, principal.user_id)
    base = {"user_id": principal.user_id, "platform_admin": principal.is_platform_admin, "email": u.email if u else None, "username": u.username if u else None,
            "mfa_verified": principal.mfa_verified_at is not None, "mfa_enabled": bool(u and pl.mfa_method(u)), "mfa_method": pl.mfa_method(u) if u else None,
            "mfa_required": bool(u and _pl.needs_mfa(db, u) and principal.mfa_verified_at is None),
            "idp": "dev-local" if settings.dev_idp_enabled else "password" if (u and u.password_hash) else "oidc"}
    if principal.tenant_id is None:
        return {**base, "tenant_id": None, "permissions": [], "site_ids": [], "customer_ids": [], "provider_ids": [], "roles": []}
    scope = resolve_access_scope(PrincipalContext(
        principal_type=principal.principal_type, tenant_id=principal.tenant_id, user_id=principal.user_id,
        roles=principal.roles, site_grants=principal.site_ids, customer_grants=principal.customer_ids,
        provider_grants=principal.provider_ids))
    return {**base, "tenant_id": principal.tenant_id, "roles": sorted(principal.roles),
            "permissions": sorted(scope.permissions), "site_ids": sorted(scope.site_ids),
            "customer_ids": sorted(scope.customer_ids), "provider_ids": sorted(scope.provider_ids)}


# ---------------------------------------------------------------- username / password + TOTP
from fastapi import Body  # noqa: E402

from app.core import passwords, password_login as pl  # noqa: E402
from app.db import begin_auth_lookup  # noqa: E402
from app.models.identity import TempoUser  # noqa: E402


def _cid(request: Request) -> str:
    return getattr(request.state, "correlation_id", "n/a")


class PasswordLogin(BaseModel):
    username: str
    password: str


class MfaVerify(BaseModel):
    challenge: str
    code: str


def _session_response(response: Response, issued: auth.IssuedSession, extra: dict | None = None) -> dict:
    _set_session_cookies(response, issued)
    return {"status": "signed_in", "expires_at": issued.access_expires_at.isoformat(), **(extra or {})}


@router.post("/auth/login")
def password_login(body: PasswordLogin, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    out = pl.password_login(db, request, body.username, body.password, _cid(request))
    if out.kind == "mfa_required":
        return {"status": "mfa_required", "challenge": out.challenge, "method": out.method, "sent": out.sent, "hint": out.hint}
    return _session_response(response, out.issued, {"mfa_enrol_required": out.kind == "mfa_enrol_required"})


@router.post("/auth/mfa/verify")
def mfa_verify(body: MfaVerify, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    return _session_response(response, pl.mfa_verify(db, request, body.challenge, body.code, _cid(request)))


class Code(BaseModel):
    code: str


class Challenge(BaseModel):
    challenge: str


@router.post("/auth/mfa/email/resend")
def mfa_email_resend(body: Challenge, request: Request, db: Session = Depends(get_db)) -> dict:
    return pl.mfa_resend(db, request, body.challenge, _cid(request))


@router.post("/auth/mfa/email/enroll")
def mfa_email_enroll(request: Request, principal: auth.ResolvedPrincipal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    """Starts email-code enrolment: emails a code to the account's address. It turns on only after the code is entered."""
    from app.core import email_otp
    pl.require_secure_transport(request)
    begin_auth_lookup(db)
    user = db.get(TempoUser, principal.user_id)
    if pl.mfa_method(user):
        raise AuthInvalid("A second factor is already set up. Ask an administrator to reset it first.")
    email_otp.require_ready(db, user)
    sent = email_otp.issue(db, user, "enrol")
    if not sent:
        raise AuthInvalid("The code email could not be sent. Check the platform email settings, or use an authenticator app.")
    return {"sent_to": email_otp.mask(user.email)}


@router.post("/auth/mfa/email/confirm")
def mfa_email_confirm(body: Code, request: Request, principal: auth.ResolvedPrincipal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    from datetime import datetime, timezone
    from app.core import email_otp
    from app.models.identity import UserSession
    pl.require_secure_transport(request)
    begin_auth_lookup(db)
    user = db.get(TempoUser, principal.user_id)
    if pl.mfa_method(user) or not email_otp.verify(db, user, "enrol", body.code):
        raise AuthInvalid("That code is not valid, or it has expired. Request a new one.")
    now = datetime.now(timezone.utc)
    user.email_mfa_enabled_at = now
    sess = db.get(UserSession, principal.session_id)
    sess.mfa_verified_at = now
    auth.audit(db, actor_type="user", actor_id=user.user_id, action="mfa.enrolled", decision="allowed", reason_code="email", correlation_id=_cid(request))
    return {"status": "mfa_enabled"}


@router.post("/auth/mfa/enroll")
def mfa_enroll(request: Request, principal: auth.ResolvedPrincipal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    """Starts TOTP enrolment for the signed-in user. The secret is shown once; it becomes active only after a valid code."""
    pl.require_secure_transport(request)
    begin_auth_lookup(db)
    user = db.get(TempoUser, principal.user_id)
    if pl.mfa_method(user):
        raise AuthInvalid("A second factor is already set up. Ask an administrator to reset it if you lost your device.")
    secret = passwords.new_totp_secret()
    user.totp_secret_enc = passwords.encrypt_secret(secret, settings.session_signing_key or auth._signing_key())
    return {"secret": secret, "otpauth_uri": passwords.otpauth_uri(secret, user.email or user.username or user.user_id)}


@router.post("/auth/mfa/confirm")
def mfa_confirm(body: Code, request: Request, principal: auth.ResolvedPrincipal = Depends(get_principal), db: Session = Depends(get_db)) -> dict:
    from datetime import datetime, timezone
    from app.models.identity import UserSession

    begin_auth_lookup(db)
    user = db.get(TempoUser, principal.user_id)
    secret = passwords.decrypt_secret(user.totp_secret_enc, settings.session_signing_key or auth._signing_key()) if user.totp_secret_enc else None
    step = passwords.verify_totp(secret, body.code, user.totp_last_step) if secret and user.totp_enabled_at is None else None
    if step is None:
        raise AuthInvalid("That code is not valid. Check the time on your device and try again.")
    now = datetime.now(timezone.utc)
    user.totp_enabled_at, user.totp_last_step = now, step
    sess = db.get(UserSession, principal.session_id)
    sess.mfa_verified_at = now
    auth.audit(db, actor_type="user", actor_id=user.user_id, action="mfa.enrolled", decision="allowed", correlation_id=_cid(request))
    return {"status": "mfa_enabled"}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/auth/password")
def change_password(body: PasswordChange, request: Request, response: Response, principal: auth.ResolvedPrincipal = Depends(get_principal),
                    db: Session = Depends(get_db)) -> dict:
    from datetime import datetime, timezone
    from app.errors import ScopeError

    pl.require_secure_transport(request)
    begin_auth_lookup(db)
    user = db.get(TempoUser, principal.user_id)
    ok, _ = passwords.verify_password(user.password_hash, body.current_password)
    if not ok:
        auth.audit(db, actor_type="user", actor_id=user.user_id, action="password.change", decision="denied", reason_code="bad_current", correlation_id=_cid(request))
        db.commit()
        raise AuthInvalid("Your current password is not correct.")
    problems = passwords.policy_problems(body.new_password, username=user.username, email=user.email)
    if problems or body.new_password == body.current_password:
        raise ScopeError("New password: " + ("; ".join(problems) or "choose a different password"))
    user.password_hash, user.password_changed_at = passwords.hash_password(body.new_password), datetime.now(timezone.utc)
    mfa = principal.mfa_verified_at is not None
    auth.revoke_user_everywhere(db, user.user_id, reason="password_changed", correlation_id=_cid(request))  # signs out every other device
    db.flush()
    issued = auth.create_session(db, user, mfa=mfa, auth_method="password")
    auth.audit(db, actor_type="user", actor_id=user.user_id, action="password.change", decision="allowed", correlation_id=_cid(request))
    return _session_response(response, issued)


class Invitation(BaseModel):
    token: str
    password: str
    username: str | None = None


@router.get("/auth/invite/{token}")
def invite_info(token: str, db: Session = Depends(get_db)) -> dict:
    inv, user = pl.load_invitation(db, token)
    return {"email": user.email, "username": user.username, "purpose": inv.purpose, "expires_at": inv.expires_at.isoformat(),
            "password_rules": {"min_length": passwords.MIN_LEN, "max_length": passwords.MAX_LEN}}


@router.post("/auth/accept-invite")
def accept_invite(body: Invitation, request: Request, db: Session = Depends(get_db)) -> dict:
    user = pl.accept_invitation(db, request, body.token, body.password, body.username, _cid(request))
    return {"status": "password_set", "username": user.username}
