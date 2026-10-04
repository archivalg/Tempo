"""Outgoing email (SMTP). The platform's account is configured by a platform admin and stored encrypted; nothing here is tenant data.

* Sending is best-effort: an invitation still works (the one-time link is shown on screen) when email is off or fails; the result is logged without the body.
* The password is only ever decrypted to log in to the SMTP server. No API returns it.
* Connection tests log in WITHOUT sending a message; a test email is a separate, explicit action.
"""
from __future__ import annotations

import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage as Mime
from email.utils import formataddr

from sqlalchemy.orm import Session

from app.config import settings
from app.core import auth, passwords
from app.models.billing import EmailMessage, SmtpConfig

TIMEOUT = 15
SECURITIES = ("starttls", "ssl", "none")


def _key() -> str:
    return settings.session_signing_key or auth._signing_key()


def encrypt(password: str) -> str:
    return passwords.encrypt_secret(password, _key())


def _password(cfg: SmtpConfig) -> str | None:
    return passwords.decrypt_secret(cfg.password_enc, _key()) if cfg.password_enc else None


def get_config(db: Session) -> SmtpConfig | None:
    return db.get(SmtpConfig, "default")


def public_view(cfg: SmtpConfig | None) -> dict:
    c = cfg or SmtpConfig()
    return {"enabled": bool(c.enabled), "host": c.host or "", "port": c.port or 587, "security": c.security or "starttls", "username": c.username or "", "has_password": bool(c.password_enc),
            "from_email": c.from_email or "", "from_name": c.from_name or "Tempo", "configured": bool(cfg and cfg.host and cfg.from_email), "updated_by": (c.updated_by or None), "updated_at": c.updated_at if cfg else None,
            "last_test_at": c.last_test_at, "last_test_ok": c.last_test_ok, "last_test_detail": c.last_test_detail}


def _connect(host: str, port: int, security: str, username: str, password: str | None) -> smtplib.SMTP:
    ctx = ssl.create_default_context()
    if security == "ssl":
        s: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=TIMEOUT, context=ctx)
    else:
        s = smtplib.SMTP(host, port, timeout=TIMEOUT)
        s.ehlo()
        if security == "starttls":
            s.starttls(context=ctx)
            s.ehlo()
    if username and password:
        s.login(username, password)
    return s


def _explain(e: Exception) -> str:
    if isinstance(e, smtplib.SMTPAuthenticationError):
        return "The mail server refused the username or password (some providers also need SMTP sign-in enabled for the mailbox)."
    if isinstance(e, (TimeoutError, OSError)):
        return f"Could not reach the mail server ({type(e).__name__}). Check the host, port and that this server may connect out."
    if isinstance(e, smtplib.SMTPException):
        return f"The mail server answered with an error ({type(e).__name__})."
    return f"Could not connect ({type(e).__name__})."


def test_connection(db: Session, cfg: SmtpConfig) -> tuple[bool, str]:
    """Connects and logs in. Sends no message. Records the outcome on the configuration."""
    try:
        s = _connect(cfg.host, cfg.port, cfg.security, cfg.username, _password(cfg))
        s.quit()
        ok, detail = True, "Connected and signed in. No message was sent."
    except Exception as e:  # noqa: BLE001
        ok, detail = False, _explain(e)
    cfg.last_test_at, cfg.last_test_ok, cfg.last_test_detail = datetime.now(timezone.utc), ok, detail
    return ok, detail


def send(db: Session, to: str, subject: str, text: str, *, kind: str, tenant_id: str | None = None, created_by: str | None = None) -> bool:
    """Sends one email if email is configured and enabled. Never raises; logs what happened (not the body). Returns True only if the server accepted it."""
    cfg = get_config(db)
    if cfg is None or not cfg.enabled or not cfg.host or not cfg.from_email:
        db.add(EmailMessage(tenant_id=tenant_id, to_address=to, subject=subject, kind=kind, status="not_configured", created_by=created_by))
        return False
    m = Mime()
    m["From"], m["To"], m["Subject"] = formataddr((cfg.from_name or "Tempo", cfg.from_email)), to, subject
    m.set_content(text)
    try:
        s = _connect(cfg.host, cfg.port, cfg.security, cfg.username, _password(cfg))
        try:
            s.send_message(m)
        finally:
            s.quit()
        db.add(EmailMessage(tenant_id=tenant_id, to_address=to, subject=subject, kind=kind, status="sent", created_by=created_by))
        return True
    except Exception as e:  # noqa: BLE001
        db.add(EmailMessage(tenant_id=tenant_id, to_address=to, subject=subject, kind=kind, status="failed", error=_explain(e), created_by=created_by))
        return False


def invitation_text(*, link: str, who: str, org: str | None, purpose: str = "invite", hours: int | None = None) -> tuple[str, str]:
    ttl = hours if hours is not None else settings.invite_ttl_hours
    if purpose == "reset":
        return "Reset your Tempo password", (f"Hello,\n\nA password reset was requested for your Tempo account.\n\nOpen this link to choose a new password (it works once and expires in {ttl} hours):\n{link}\n\n"
                                              "If you did not expect this, ignore this email and tell your administrator.\n\nTempo")
    org_line = f" at {org}" if org else ""
    return "You have been invited to Tempo", (f"Hello,\n\n{who} has invited you to Tempo{org_line}.\n\nOpen this link to choose your username and password (it works once and expires in {ttl} hours):\n{link}\n\n"
                                              "Tempo will never ask for your password by email.\n\nTempo")


def invite_link(token: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/invite?token={token}"


def send_invitation(db: Session, to: str | None, token: str, *, who: str, org: str | None, purpose: str = "invite", tenant_id: str | None = None, created_by: str | None = None) -> str:
    """Emails a one-time invitation / reset link. Returns 'sent', 'failed', 'not_configured' or 'no_address'. The link is also shown on screen by the caller, so a failure never blocks the invitation."""
    if not to:
        return "no_address"
    subject, text = invitation_text(link=invite_link(token), who=who, org=org, purpose=purpose)
    ok = send(db, to, subject, text, kind="password_reset" if purpose == "reset" else "invitation", tenant_id=tenant_id, created_by=created_by)
    if ok:
        return "sent"
    cfg = get_config(db)
    return "not_configured" if cfg is None or not cfg.enabled or not cfg.host or not cfg.from_email else "failed"
