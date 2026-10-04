"""Email one-time codes for the second sign-in step.

* 6 digits, valid 10 minutes, single use, at most 5 wrong attempts per code; a new code voids the previous one.
* At most 5 codes per person per 10 minutes (so the mail server and the person's inbox cannot be flooded).
* Only a keyed hash is stored; the email log records that a code was sent, never the code.
* An email code is only as strong as the mailbox that receives it: the authenticator app remains the stronger option.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.core import auth, email as mail
from app.errors import AuthInvalid, ScopeError
from app.models.identity import EmailOtp, TempoUser

TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5
MAX_CODES_PER_WINDOW = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _hash(user_id: str, otp_id: str, code: str) -> str:
    key = (settings.session_signing_key or auth._signing_key()).encode()
    return hmac.new(key, f"{user_id}:{otp_id}:{code}".encode(), hashlib.sha256).hexdigest()


def mask(email: str | None) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1]}{'*' * max(2, min(len(local) - 1, 6))}@{domain}"


def email_available(db: Session) -> bool:
    cfg = mail.get_config(db)
    return bool(cfg and cfg.enabled and cfg.host and cfg.from_email)


def issue(db: Session, user: TempoUser, purpose: str) -> bool:
    """Creates and emails a code. Returns True if the mail server accepted it. Raises AuthInvalid when the person has asked for too many."""
    if not user.email:
        return False
    since = _now() - TTL
    recent = len(list(db.scalars(select(EmailOtp.id).where(EmailOtp.user_id == user.user_id, EmailOtp.created_at > since))))
    if recent >= MAX_CODES_PER_WINDOW:
        raise AuthInvalid("Too many codes were requested. Wait a few minutes and try again.")
    db.execute(update(EmailOtp).where(EmailOtp.user_id == user.user_id, EmailOtp.purpose == purpose, EmailOtp.consumed_at.is_(None)).values(consumed_at=_now()))
    code = f"{secrets.randbelow(10**6):06d}"
    row = EmailOtp(user_id=user.user_id, purpose=purpose, code_hash="", expires_at=_now() + TTL)
    db.add(row)
    db.flush()
    row.code_hash = _hash(user.user_id, row.id, code)
    action = "sign in to" if purpose == "login" else "turn on two-step verification for"
    ok = mail.send(db, user.email, "Your Tempo verification code",
                   f"Your Tempo verification code is {code}.\n\nIt lets you {action} your account, works once and expires in 10 minutes.\n"
                   "If you did not try this, ignore this email and change your password.\n\nTempo", kind="mfa_code")
    db.commit()   # the code must exist before the person can submit it, and the failure counters must survive a rejected request
    return ok


def verify(db: Session, user: TempoUser, purpose: str, code: str) -> bool:
    """True once for a correct, unexpired code. Wrong tries count against the code and spend it after MAX_ATTEMPTS."""
    code = (code or "").strip().replace(" ", "")
    row = db.scalar(select(EmailOtp).where(EmailOtp.user_id == user.user_id, EmailOtp.purpose == purpose, EmailOtp.consumed_at.is_(None)).order_by(EmailOtp.created_at.desc()).limit(1))
    if row is None or _aware(row.expires_at) < _now():
        return False
    row.attempts += 1
    good = len(code) == 6 and code.isdigit() and hmac.compare_digest(_hash(user.user_id, row.id, code), row.code_hash)
    if good or row.attempts >= MAX_ATTEMPTS:
        row.consumed_at = _now()
    db.commit()
    return good


def require_ready(db: Session, user: TempoUser) -> None:
    if not user.email:
        raise ScopeError("Your account has no email address to send codes to.")
    if not email_available(db):
        raise ScopeError("Email is not set up on this platform yet, so email codes are unavailable. Use an authenticator app instead.")
