"""Username/password sign-in with lockout, throttling, TOTP step-up and invitations.

Security properties (each covered by tests/test_password_login.py):
* a wrong username and a wrong password are indistinguishable (same message, one Argon2 verification either way);
* N consecutive failures lock the account for a cooling-off period (correct password is refused while locked);
* a per-address throttle slows credential stuffing across many accounts;
* admins (tenant_admin / platform admin) must have TOTP; without it their session carries no admin authority;
* TOTP codes are single-use (replay blocked); the secret is encrypted at rest;
* invitations are single-use, expire, and only a digest is stored; there is no default password anywhere;
* outside local/test, password sign-in refuses plain HTTP so credentials never cross the network in clear.
"""
from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Request
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core import auth, passwords
from app.db import begin_auth_lookup
from app.errors import AuthForbidden, AuthInvalid, ScopeError
from app.models.identity import PlatformAdmin, TempoUser, TenantMembership, UserInvitation, UserRoleAssignment

GENERIC = "Incorrect username or password, or the account is temporarily locked."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


# ---- transport + throttle -------------------------------------------------
def require_secure_transport(request: Request) -> None:
    if not settings.require_https or settings.env in ("local", "test"):
        return
    scheme = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip().lower()
    if scheme != "https":
        raise AuthForbidden("Sign-in requires a secure (HTTPS) connection. Ask an administrator to enable HTTPS for this site.")


class _Throttle:
    def __init__(self) -> None:
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window: float = 600.0) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def reset(self) -> None:
        self.hits.clear()


throttle = _Throttle()


def client_ip(request: Request) -> str:
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def normalise(identifier: str) -> str:
    return identifier.strip().lower()


def _audit(db: Session, user_id: str | None, ident: str, action: str, decision: str, reason: str, cid: str, ip: str) -> None:
    actor = user_id or "anon:" + auth.digest(ident)[:12]  # never the raw identifier of an unknown account
    auth.audit(db, actor_type="user" if user_id else "anonymous", actor_id=actor, action=action, decision=decision, reason_code=f"{reason};ip={ip}", correlation_id=cid)


# ---- lookup ----------------------------------------------------------------
def find_user(db: Session, ident: str) -> TempoUser | None:
    begin_auth_lookup(db)
    return db.scalar(select(TempoUser).where(or_(TempoUser.username == ident, TempoUser.email == ident)).limit(1))


def needs_mfa(db: Session, user: TempoUser) -> bool:
    """Admins must use a second factor (Blueprint §5.1)."""
    if db.get(PlatformAdmin, user.user_id) is not None:
        return True
    roles = db.scalars(select(UserRoleAssignment.role).where(UserRoleAssignment.user_id == user.user_id)).all()
    return any(r in auth.MFA_REQUIRED_ROLES for r in roles)


def has_access(db: Session, user: TempoUser) -> bool:
    if db.get(PlatformAdmin, user.user_id) is not None:
        return True
    return db.scalar(select(TenantMembership.user_id).where(TenantMembership.user_id == user.user_id, TenantMembership.status == "active").limit(1)) is not None


@dataclass
class LoginOutcome:
    kind: str  # session | mfa_required | mfa_enrol_required
    issued: auth.IssuedSession | None = None
    challenge: str | None = None


def _mfa_challenge(user_id: str) -> str:
    return jwt.encode({"typ": "mfa", "sub": user_id, "exp": int((_now() + timedelta(minutes=5)).timestamp()), "jti": secrets.token_hex(8)}, auth._signing_key(), algorithm="HS256")


def _fail(db: Session, user: TempoUser | None, ident: str, reason: str, cid: str, ip: str) -> None:
    if user is not None:
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= settings.login_max_failures:
            user.locked_until = _now() + timedelta(minutes=settings.login_lock_minutes)
            user.failed_logins = 0
            _audit(db, user.user_id, ident, "login.locked", "applied", "too_many_failures", cid, ip)
    _audit(db, user.user_id if user else None, ident, "login", "denied", reason, cid, ip)
    db.commit()  # failures must persist even though the request is rejected


def password_login(db: Session, request: Request, identifier: str, password: str, cid: str) -> LoginOutcome:
    require_secure_transport(request)
    ip, ident = client_ip(request), normalise(identifier)
    if not settings.password_auth_enabled:
        raise AuthInvalid(GENERIC)
    if not (throttle.check(f"ip:{ip}", settings.login_ip_limit) and throttle.check(f"ipu:{ip}:{ident}", 10)):
        begin_auth_lookup(db)   # the audit row is written outside any tenant: without this the refusal became a server error
        _audit(db, None, ident, "login", "denied", "throttled", cid, ip)
        db.commit()
        raise AuthInvalid(GENERIC)
    user = find_user(db, ident)
    ok, rehash = passwords.verify_password(user.password_hash if user else None, password)
    locked = bool(user and _aware(user.locked_until) and _aware(user.locked_until) > _now())
    if not ok or locked or user is None or user.account_status != "active":
        _fail(db, user if not locked else None, ident, "locked" if locked else "bad_credentials", cid, ip)
        raise AuthInvalid(GENERIC)
    if not has_access(db, user):
        _audit(db, user.user_id, ident, "login", "denied", "no_access", cid, ip)
        db.commit()
        raise AuthForbidden("This account has no access to any workspace. Contact your administrator.")
    user.failed_logins, user.locked_until = 0, None
    if rehash:
        user.password_hash = passwords.hash_password(password)
    if user.totp_enabled_at is not None:
        _audit(db, user.user_id, ident, "login.password_ok", "allowed", "mfa_required", cid, ip)
        db.commit()
        return LoginOutcome("mfa_required", challenge=_mfa_challenge(user.user_id))
    issued = auth.create_session(db, user, mfa=False, auth_method="password")
    _audit(db, user.user_id, ident, "login", "allowed", "password_only", cid, ip)
    return LoginOutcome("mfa_enrol_required" if needs_mfa(db, user) else "session", issued=issued)


def mfa_verify(db: Session, request: Request, challenge: str, code: str, cid: str) -> auth.IssuedSession:
    require_secure_transport(request)
    ip = client_ip(request)
    try:
        claims = jwt.decode(challenge, auth._signing_key(), algorithms=["HS256"])
        if claims.get("typ") != "mfa":
            raise jwt.PyJWTError()
    except jwt.PyJWTError:
        raise AuthInvalid("Your sign-in expired. Start again.") from None
    if not throttle.check(f"mfa:{ip}:{claims['sub']}", 10):
        raise AuthInvalid("Too many attempts. Wait a few minutes and start again.")
    begin_auth_lookup(db)
    user = db.get(TempoUser, claims["sub"])
    secret = passwords.decrypt_secret(user.totp_secret_enc, settings.session_signing_key or auth._signing_key()) if user and user.totp_secret_enc else None
    step = passwords.verify_totp(secret, code, user.totp_last_step) if secret and user.totp_enabled_at else None
    if user is None or step is None or user.account_status != "active" or (_aware(user.locked_until) and _aware(user.locked_until) > _now()):
        _fail(db, user, user.username if user and user.username else "?", "bad_totp", cid, ip)
        raise AuthInvalid("That code is not valid. Try the next code from your authenticator app.")
    user.totp_last_step, user.failed_logins = step, 0
    issued = auth.create_session(db, user, mfa=True, auth_method="password+totp")
    _audit(db, user.user_id, user.username or "", "login", "allowed", "password+totp", cid, ip)
    return issued


# ---- invitations -----------------------------------------------------------
def create_invitation(db: Session, user: TempoUser, created_by: str | None, purpose: str = "invite") -> str:
    """Returns the one-time token (shown once). Any earlier unused invitation for the user is voided."""
    begin_auth_lookup(db)
    for old in db.scalars(select(UserInvitation).where(UserInvitation.user_id == user.user_id, UserInvitation.used_at.is_(None))):
        old.used_at = _now()
    token = secrets.token_urlsafe(32)
    db.add(UserInvitation(user_id=user.user_id, token_digest=auth.digest(token), purpose=purpose, created_by=created_by,
                          expires_at=_now() + timedelta(hours=settings.invite_ttl_hours)))
    db.flush()
    return token


def load_invitation(db: Session, token: str) -> tuple[UserInvitation, TempoUser]:
    begin_auth_lookup(db)
    inv = db.scalar(select(UserInvitation).where(UserInvitation.token_digest == auth.digest(token)))
    user = db.get(TempoUser, inv.user_id) if inv else None
    if inv is None or user is None or inv.used_at is not None or _aware(inv.expires_at) <= _now() or user.account_status != "active":
        raise AuthInvalid("This invitation link is invalid or has expired. Ask for a new one.")
    return inv, user


def accept_invitation(db: Session, request: Request, token: str, password: str, username: str | None, cid: str) -> TempoUser:
    require_secure_transport(request)
    ip = client_ip(request)
    if not throttle.check(f"inv:{ip}", 20):
        raise AuthInvalid("Too many attempts. Try again later.")
    inv, user = load_invitation(db, token)
    uname = normalise(username) if username else (user.username or user.email)
    if not uname or len(uname) < 3 or len(uname) > 80 or " " in uname:
        raise ScopeError("choose a username of 3-80 characters without spaces")
    taken = db.scalar(select(TempoUser).where(TempoUser.username == uname, TempoUser.user_id != user.user_id))
    if taken is not None:
        raise ScopeError("that username is not available")
    problems = passwords.policy_problems(password, username=uname, email=user.email)
    if problems:
        raise ScopeError("Password: " + "; ".join(problems))
    user.username, user.password_hash, user.password_changed_at = uname, passwords.hash_password(password), _now()
    user.failed_logins, user.locked_until = 0, None
    inv.used_at = _now()
    _audit(db, user.user_id, uname, f"password.{inv.purpose}_accepted", "allowed", "one_time_token", cid, ip)
    return user
