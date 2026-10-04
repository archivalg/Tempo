"""Platform SMTP configuration: encrypted password, never returned, test connection sends nothing, invitations are emailed best-effort and logged without bodies."""
from __future__ import annotations

import smtplib

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.billing import EmailMessage, SmtpConfig

from .test_platform import _admin_headers, _bootstrap

PASSWORD = "Sup3r-Secret-Pa55word!"


@pytest.fixture(autouse=True)
def _http_cookies(monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", False)


class FakeSMTP:
    sent: list = []
    logins: list = []
    fail_login = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def ehlo(self): pass
    def starttls(self, context=None): pass

    def login(self, u, p):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"bad")
        FakeSMTP.logins.append((u, p))

    def send_message(self, m): FakeSMTP.sent.append(m)
    def quit(self): pass


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.sent, FakeSMTP.logins, FakeSMTP.fail_login = [], [], False
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


CFG = {"enabled": True, "host": "smtp.example.test", "port": 587, "security": "starttls", "username": "mailer@example.test", "password": PASSWORD, "from_email": "mailer@example.test", "from_name": "Tempo"}


def test_password_is_encrypted_write_only_and_blank_keeps_it(client, smtp):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    r = client.put("/v1/platform/email", headers=h, json=CFG)
    assert r.status_code == 200, r.text
    assert PASSWORD not in r.text and r.json()["has_password"] is True and "password" not in r.json()
    assert PASSWORD not in client.get("/v1/platform/email", headers=h).text
    with client.session_local() as s:
        enc = s.get(SmtpConfig, "default").password_enc
    assert enc and PASSWORD not in enc
    body = {**CFG, "password": "", "from_name": "Tempo Test"}
    assert client.put("/v1/platform/email", headers=h, json=body).status_code == 200
    with client.session_local() as s:
        assert s.get(SmtpConfig, "default").password_enc == enc
    assert client.post("/v1/platform/email/test-connection", headers=h).json()["ok"] is True
    assert smtp.logins == [("mailer@example.test", PASSWORD)] and smtp.sent == []   # logging in sends nothing


def test_failed_login_is_reported_plainly(client, smtp):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    client.put("/v1/platform/email", headers=h, json=CFG)
    smtp.fail_login = True
    r = client.post("/v1/platform/email/test-connection", headers=h).json()
    assert r["ok"] is False and "username or password" in r["detail"] and PASSWORD not in r["detail"]
    assert client.get("/v1/platform/email", headers=h).json()["last_test_ok"] is False


def test_enabling_needs_host_and_from_and_tenant_users_cannot_reach_it(client, smtp):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    assert client.put("/v1/platform/email", headers=h, json={**CFG, "host": ""}).status_code == 400
    assert client.put("/v1/platform/email", headers=h, json={**CFG, "security": "bogus"}).status_code == 400
    assert client.get("/v1/platform/email").status_code in (401, 403)


def test_send_test_and_log_has_no_body(client, smtp):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    client.put("/v1/platform/email", headers=h, json=CFG)
    r = client.post("/v1/platform/email/send-test", headers=h, json={"to": "someone@example.test"})
    assert r.json()["sent"] is True and len(smtp.sent) == 1 and smtp.sent[0]["To"] == "someone@example.test"
    log = client.get("/v1/platform/email/messages", headers=h).json()
    assert log[0]["status"] == "sent" and log[0]["kind"] == "test" and set(log[0]) == {"id", "at", "to", "subject", "kind", "status", "error", "tenant_id"}


def test_platform_invitations_are_emailed_with_the_link_and_still_shown(client, smtp):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    client.put("/v1/platform/email", headers=h, json=CFG)
    r = client.post("/v1/platform/admins", headers=h, json={"email": "second@example.test"})
    assert r.status_code == 201 and r.json()["emailed"] == "sent" and r.json()["invite_token"]
    m = smtp.sent[-1]
    assert m["To"] == "second@example.test" and r.json()["invite_token"] in m.get_content() and "/invite?token=" in m.get_content()
    t = client.post("/v1/platform/tenants", headers=h, json={"tenant_id": "acme", "name": "Acme", "first_admin": {"email": "boss@example.test"}, "initial_site_ids": ["s1"]})
    assert t.status_code == 201 and t.json()["emailed"] == "sent" and "Acme" in smtp.sent[-1].get_content()
    with client.session_local() as s:
        assert all(x.status == "sent" for x in s.scalars(select(EmailMessage)))


def test_invitation_still_works_when_email_is_not_configured_or_fails(client, smtp):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    r = client.post("/v1/platform/admins", headers=h, json={"email": "a@example.test"})
    assert r.status_code == 201 and r.json()["emailed"] == "not_configured" and r.json()["invite_token"]
    client.put("/v1/platform/email", headers=h, json=CFG)
    smtp.fail_login = True
    r = client.post("/v1/platform/admins", headers=h, json={"email": "b@example.test"})
    assert r.status_code == 201 and r.json()["emailed"] == "failed" and r.json()["invite_token"]
    log = client.get("/v1/platform/email/messages", headers=h).json()
    assert {m["status"] for m in log} == {"failed", "not_configured"}


def test_email_log_is_tenant_isolated_for_tenant_sessions(client):
    from app import db as db_module
    with client.session_local() as s:
        s.add(EmailMessage(tenant_id="ten_a", to_address="a@example.test", subject="x", kind="invitation", status="sent"))
        s.add(EmailMessage(tenant_id=None, to_address="p@example.test", subject="x", kind="test", status="sent"))
        s.commit()
    with db_module.tenant_session("ten_a") as s:
        assert [m.to_address for m in s.scalars(select(EmailMessage))] == ["a@example.test"]
    with db_module.tenant_session("ten_b") as s:
        assert list(s.scalars(select(EmailMessage))) == []
