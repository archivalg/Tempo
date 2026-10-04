"""Email-code second factor: enrol, sign in, single use, attempt limit, expiry, resend, refusal when email is off or another factor exists."""
from __future__ import annotations

import re
import smtplib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.core import email as mail, password_login as pl
from app.models.billing import EmailMessage, SmtpConfig
from app.models.identity import EmailOtp

from .test_email import FakeSMTP
from .test_password_login import login, mkuser


@pytest.fixture(autouse=True)
def _relax(monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    pl.throttle.reset()
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.fail_login = [], [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)


def configure_email(client):
    with client.session_local() as s:
        s.add(SmtpConfig(id="default", enabled=True, host="smtp.example.test", port=587, security="starttls", username="m@example.test", password_enc=mail.encrypt("pw"), from_email="m@example.test"))
        s.commit()


def last_code() -> str:
    m = FakeSMTP.sent[-1]
    return re.search(r"code is (\d{6})", m.get_content()).group(1)


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("tempo_csrf")}


def enrol(client):
    assert client.post("/v1/auth/mfa/email/enroll", headers=csrf(client)).status_code == 200
    return client.post("/v1/auth/mfa/email/confirm", json={"code": last_code()}, headers=csrf(client))


def test_enrol_by_email_then_sign_in_needs_a_fresh_single_use_code(client):
    configure_email(client)
    mkuser(client, "boss@example.test", "boss", roles=("tenant_admin",))
    assert login(client, "boss").json()["mfa_enrol_required"] is True
    r = client.post("/v1/auth/mfa/email/enroll", headers=csrf(client))
    assert r.status_code == 200 and r.json()["sent_to"].startswith("b") and "boss@" not in r.text
    assert client.post("/v1/auth/mfa/email/confirm", json={"code": "000000"}, headers=csrf(client)).status_code == 401
    ok = client.post("/v1/auth/mfa/email/confirm", json={"code": last_code()}, headers=csrf(client))
    assert ok.status_code == 200
    me = client.get("/v1/me/access").json()
    assert me["mfa_enabled"] and me["mfa_method"] == "email" and "labour.configure" in me["permissions"]
    client.cookies.clear()

    n = len(FakeSMTP.sent)
    r2 = login(client, "boss").json()
    assert r2["status"] == "mfa_required" and r2["method"] == "email" and r2["sent"] is True and len(FakeSMTP.sent) == n + 1 and "tempo_at" not in client.cookies
    code = last_code()
    wrong = "000000" if code != "000000" else "111111"
    assert client.post("/v1/auth/mfa/verify", json={"challenge": r2["challenge"], "code": wrong}).status_code == 401
    assert client.post("/v1/auth/mfa/verify", json={"challenge": r2["challenge"], "code": code}).status_code == 200
    assert client.get("/v1/me/access").json()["mfa_verified"] is True
    client.cookies.clear()
    assert client.post("/v1/auth/mfa/verify", json={"challenge": r2["challenge"], "code": code}).status_code == 401   # single use
    with client.session_local() as s:   # the code is never stored or logged in clear
        assert all(code not in o.code_hash for o in s.scalars(select(EmailOtp)))
        assert all(code not in (m.subject + (m.error or "")) for m in s.scalars(select(EmailMessage)))
        assert {m.kind for m in s.scalars(select(EmailMessage))} == {"mfa_code"}


def test_five_wrong_tries_spend_the_code_and_resend_voids_the_old_one(client):
    configure_email(client)
    mkuser(client, "boss@example.test", "boss", roles=("tenant_admin",))
    login(client, "boss")
    enrol(client)
    client.cookies.clear()
    ch = login(client, "boss").json()["challenge"]
    first = last_code()
    wrong = "000000" if first != "000000" else "111111"
    for _ in range(5):
        assert client.post("/v1/auth/mfa/verify", json={"challenge": ch, "code": wrong}).status_code == 401
    assert client.post("/v1/auth/mfa/verify", json={"challenge": ch, "code": first}).status_code == 401   # spent by the failed tries
    pl.throttle.reset()
    with client.session_local() as s:   # clear the per-account lock from the failures so we can test resend
        from app.models.identity import TempoUser
        for u in s.scalars(select(TempoUser)):
            u.locked_until, u.failed_logins = None, 0
        s.commit()
    r = client.post("/v1/auth/mfa/email/resend", json={"challenge": ch})
    assert r.status_code == 200 and r.json()["sent"] is True
    second = last_code()
    assert client.post("/v1/auth/mfa/verify", json={"challenge": ch, "code": second}).status_code == 200


def test_expired_code_is_refused(client):
    configure_email(client)
    mkuser(client, "boss@example.test", "boss", roles=("tenant_admin",))
    login(client, "boss")
    enrol(client)
    client.cookies.clear()
    ch = login(client, "boss").json()["challenge"]
    code = last_code()
    with client.session_local() as s:
        for o in s.scalars(select(EmailOtp).where(EmailOtp.consumed_at.is_(None))):
            o.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    assert client.post("/v1/auth/mfa/verify", json={"challenge": ch, "code": code}).status_code == 401


def test_enrolment_refused_when_email_is_off_or_another_factor_exists(client):
    mkuser(client, "boss@example.test", "boss", roles=("tenant_admin",))
    login(client, "boss")
    r = client.post("/v1/auth/mfa/email/enroll", headers=csrf(client))
    assert r.status_code == 400 and "not set up" in r.text and FakeSMTP.sent == []
    configure_email(client)
    assert client.post("/v1/auth/mfa/email/enroll", headers=csrf(client)).status_code == 200
    assert client.post("/v1/auth/mfa/email/confirm", json={"code": last_code()}, headers=csrf(client)).status_code == 200
    assert client.post("/v1/auth/mfa/enroll", headers=csrf(client)).status_code == 401   # already has a factor
    assert client.post("/v1/auth/mfa/email/enroll", headers=csrf(client)).status_code == 401


def test_admin_reset_removes_the_email_factor(client):
    configure_email(client)
    uid = mkuser(client, "boss@example.test", "boss", roles=("tenant_admin",))
    login(client, "boss")
    enrol(client)
    from app.cli import main
    client.cookies.clear()
    assert main(["reset-mfa", "--username", "boss", "--operator", "t"]) == 0
    r = login(client, "boss").json()
    assert r["status"] == "signed_in" and r["mfa_enrol_required"] is True


def test_mobile_sign_in_uses_the_email_code_and_can_resend(client):
    configure_email(client)
    mkuser(client, "boss@example.test", "boss", roles=("tenant_admin",))
    login(client, "boss")
    enrol(client)
    client.cookies.clear()
    r = client.post("/v1/mobile/auth/login", json={"username": "boss", "password": "correct horse battery 9"}).json()
    assert r["status"] == "mfa_required" and r["method"] == "email" and r["sent"] is True
    old = last_code()
    assert client.post("/v1/mobile/auth/mfa/resend", json={"challenge": r["challenge"]}).json()["sent"] is True
    assert client.post("/v1/mobile/auth/mfa", json={"challenge": r["challenge"], "code": old}).status_code == 401 if old != last_code() else True
    ok = client.post("/v1/mobile/auth/mfa", json={"challenge": r["challenge"], "code": last_code()})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert client.post("/v1/mobile/auth/mfa/resend", json={"challenge": "junk"}).status_code == 401
