"""Gate 1 evidence: platform-admin bootstrap, separation from tenant data, tenant/support-grant lifecycle."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app import cli
from app.config import settings
from app.models.identity import PlatformAdmin, PrivilegedSupportGrant, SecurityAuditEvent, TempoUser

from .conftest import context_header


@pytest.fixture(autouse=True)
def _http_cookies(monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", False)


def _bootstrap(**kw):
    return cli.bootstrap_platform_admin(operator="ops@example.test", **kw)


def _dev_login(client, subject, email, mfa=True):
    r = client.post("/v1/auth/dev-login", json={"subject": subject, "email": email, "mfa": mfa})
    return r


def _admin_headers(client, mfa=True, subject="idp|admin", email="admin@example.test"):
    r = _dev_login(client, subject, email, mfa)
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_bootstrap_requires_explicit_identity_and_refuses_second_run(client, capsys):
    assert _bootstrap(subject=None, email=None) == 2
    assert _bootstrap(subject="idp|a", email="a@example.test") == 2
    assert _bootstrap(subject=None, email="first@example.test") == 0
    assert _bootstrap(subject="idp|other", email=None) == 3  # an initial admin exists
    with client.session_local() as s:
        assert len(s.scalars(select(PlatformAdmin)).all()) == 1
        actions = [(e.action, e.decision) for e in s.scalars(select(SecurityAuditEvent))]
        assert ("platform.bootstrap", "allowed") in actions and ("platform.bootstrap", "denied") in actions


def test_email_invitation_only_links_the_matching_verified_identity(client):
    assert _bootstrap(subject=None, email="trev@example.test") == 0
    wrong = _dev_login(client, "idp|impostor", "someone.else@example.test")
    assert wrong.status_code == 403  # display-name / other-email lookalikes get nothing
    good = _dev_login(client, "idp|real", "trev@example.test")
    assert good.status_code == 200
    with client.session_local() as s:
        u = s.scalar(select(TempoUser).where(TempoUser.email == "trev@example.test"))
        assert u.external_subject == "idp|real"  # pending invitation linked to the verified subject
        assert s.get(PlatformAdmin, u.user_id) is not None


def test_no_default_password_or_credential_is_created(client):
    _bootstrap(subject="idp|x", email=None)
    with client.session_local() as s:
        cols = set(TempoUser.__table__.columns.keys())
        assert not any("password" in c for c in cols)


def test_platform_routes_reject_tenant_users_and_non_mfa_admins(client):
    _bootstrap(subject="idp|admin", email=None)
    assert client.get("/v1/platform/tenants", headers=context_header(roles=["tenant_admin"])).status_code == 403
    assert client.get("/v1/platform/tenants").status_code == 401
    no_mfa = _admin_headers(client, mfa=False, subject="idp|admin", email="admin@example.test")
    assert client.get("/v1/platform/tenants", headers=no_mfa).status_code == 403


def test_platform_admin_has_no_ambient_tenant_data_access(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    assert client.get("/v1/platform/tenants", headers=h).status_code == 200
    # No tenant membership, no support-grant data path: tenant APIs are closed to the platform principal.
    assert client.get("/v1/data-readiness", params={"capability": "optimize.roster"}, headers=h).status_code == 403
    assert client.get("/v1/runs", headers={**h, "X-Tempo-Tenant": "ten_test"}).status_code in (403, 404)


def test_tenant_lifecycle_and_first_admin_activation(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    r = client.post("/v1/platform/tenants", headers=h, json={
        "tenant_id": "ensemble_solutions", "name": "Ensemble Solutions",
        "first_admin": {"email": "tenant.admin@example.test"}, "initial_site_ids": ["site_mel_01"]})
    assert r.status_code == 201, r.text
    # the invited admin signs in with the verified address and receives exactly the delegated scope
    login = _dev_login(client, "idp|tenantadmin", "tenant.admin@example.test", mfa=True)
    assert login.status_code == 200
    th = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.cookies.clear()
    me = client.get("/v1/me/access", headers=th).json()
    assert me["tenant_id"] == "ensemble_solutions" and me["roles"] == ["tenant_admin"] and me["site_ids"] == ["site_mel_01"]
    assert client.get("/v1/platform/tenants", headers=th).status_code == 403  # tenant admin is not a platform admin
    # suspension takes effect immediately
    assert client.post("/v1/platform/tenants/ensemble_solutions/status?status=suspended", headers=h).status_code == 200
    assert client.get("/v1/me/access", headers=th).status_code == 403
    assert client.post("/v1/platform/tenants", headers=h, json={"tenant_id": "Bad Id", "name": "Valid Name", "first_admin": {"email": "a@b.co"}, "initial_site_ids": ["s"]}).status_code == 400


def test_writeback_kill_switch_defaults_off_and_is_audited(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    client.post("/v1/platform/tenants", headers=h, json={"tenant_id": "tenant_x", "name": "Tenant X", "first_admin": {"email": "x@example.test"}, "initial_site_ids": ["s1"]})
    assert client.get("/v1/platform/tenants", headers=h).json()[0]["writeback_enabled"] is False
    assert client.post("/v1/platform/tenants/tenant_x/writeback?enabled=true", headers=h).status_code == 200
    log = client.get("/v1/platform/audit", headers=h).json()
    assert any(e["action"] == "platform.writeback_switch" for e in log)


def test_support_grant_is_time_boxed_reasoned_and_needs_distinct_approver_when_possible(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    client.post("/v1/platform/tenants", headers=h, json={"tenant_id": "tenant_x", "name": "Tenant X", "first_admin": {"email": "x@example.test"}, "initial_site_ids": ["s1"]})
    body = {"target_tenant_id": "tenant_x", "reason": "Investigating stuck run ticket 1234", "hours": 2, "action_categories": ["diagnose"], "site_ids": ["s1"]}
    assert client.post("/v1/platform/support-grants", headers=h, json={**body, "reason": "short"}).status_code == 422
    assert client.post("/v1/platform/support-grants", headers=h, json={**body, "hours": 9}).status_code == 422
    ok = client.post("/v1/platform/support-grants", headers=h, json=body)
    assert ok.status_code == 201  # sole admin: self-approval allowed but flagged in audit
    # add a second admin; now self-approval is refused
    assert client.post("/v1/platform/admins", headers=h, json={"email": "second@example.test"}).status_code == 201
    assert client.post("/v1/platform/support-grants", headers=h, json=body).status_code == 403
    with client.session_local() as s:
        g = s.scalar(select(PrivilegedSupportGrant))
        assert (g.expires_at - g.approved_at).total_seconds() <= 8 * 3600
        e = s.scalar(select(SecurityAuditEvent).where(SecurityAuditEvent.action == "support.grant_create"))
        assert e.reason_code == "sole_admin_self_approval"
