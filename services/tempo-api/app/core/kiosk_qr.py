"""Rotating QR identification for kiosks. The code is signed, expires within kiosk_qr_ttl_seconds, and works once; a photograph of it is useless a minute later."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.core import auth
from app.errors import AuthInvalid
from app.models.mobile import KioskQrNonce

PREFIX = "tqr_"


def _key() -> bytes:
    k = settings.session_signing_key or auth._signing_key()
    return k.encode() if isinstance(k, str) else k


def _sig(nonce: str, tenant_id: str, worker_id: str) -> str:
    return hmac.new(_key(), f"qr|{nonce}|{tenant_id}|{worker_id}".encode(), hashlib.sha256).hexdigest()[:32]


def issue(db: Session, tenant_id: str, worker_id: str) -> dict:
    nonce = secrets.token_urlsafe(12)
    exp = datetime.now(timezone.utc) + timedelta(seconds=settings.kiosk_qr_ttl_seconds)
    db.add(KioskQrNonce(nonce=nonce, tenant_id=tenant_id, worker_id=worker_id, expires_at=exp))
    db.flush()
    return {"token": f"{PREFIX}{nonce}.{_sig(nonce, tenant_id, worker_id)}", "expires_at": exp.isoformat(), "ttl_seconds": settings.kiosk_qr_ttl_seconds}


def redeem(db: Session, tenant_id: str, token: str, consume: bool = True) -> str:
    """Returns the worker id the code was issued to. With consume=True (a real clocking) it is spent; the kiosk's 'who is this?' preview does not spend it.
    Any problem is the same generic failure."""
    generic = AuthInvalid("credential not recognised")
    if not token.startswith(PREFIX) or "." not in token:
        raise generic
    nonce, sig = token[len(PREFIX):].split(".", 1)
    row = db.get(KioskQrNonce, nonce)
    if row is None or row.tenant_id != tenant_id or row.used_at is not None:
        raise generic
    if not hmac.compare_digest(sig, _sig(nonce, tenant_id, row.worker_id)):
        raise generic
    exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    if exp <= datetime.now(timezone.utc):
        raise generic
    if consume:
        row.used_at = datetime.now(timezone.utc)
    return row.worker_id
