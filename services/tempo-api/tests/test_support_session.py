"""Roadmap M6-ADMIN: support sessions are read-only, grant-bound, site-limited, expiring, revocable and audited under the operator's identity."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.models.canonical import Worker
from app.models.directory import Site, WorkerPerson
from app.models.identity import PrivilegedSupportGrant, SecurityAuditEvent
from app.models.rosters import RosterVersion

from .test_platform import _admin_headers, _bootstrap


@pytest.fixture(autouse=True)
def _http_cookies(monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", False)


def setup(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    assert client.post("/v1/platform/tenants", headers=h, json={"tenant_id": "tenant_x", "name": "Tenant X", "first_admin": {"email": "x@example.test"}, "initial_site_ids": ["s1", "s2"]}).status_code == 201
    with client.session_local() as s:
        for sid in ("s1", "s2"):
            s.add(Site(tenant_id="tenant_x", site_id=sid, name=f"Site {sid}", timezone="Australia/Melbourne"))
        s.flush()
        s.add(Worker(worker_id="wx1", tenant_id="tenant_x", employment_type="casual", home_site="s1", status="active"))
        s.add(Worker(worker_id="wx2", tenant_id="tenant_x", employment_type="casual", home_site="s2", status="active"))
        s.flush()
        s.add(WorkerPerson(worker_id="wx1", tenant_id="tenant_x", display_name="Secret Name", employee_no="9999"))
        s.add(RosterVersion(tenant_id="tenant_x", site_id="s1", week_start="2026-10-05", days=7, version_no=1, state="draft", source="solver", created_by="u"))
        s.add(RosterVersion(tenant_id="tenant_x", site_id="s2", week_start="2026-10-05", days=7, version_no=1, state="published", source="solver", created_by="u"))
        s.commit()
    return h


def grant(client, h, cats=("diagnostics",), sites=("s1",), hours=1):
    r = client.post("/v1/platform/support-grants", headers=h, json={"target_tenant_id": "tenant_x", "reason": "Investigating a roster problem report", "hours": hours, "action_categories": list(cats), "site_ids": list(sites)})
    assert r.status_code == 201, r.text
    return r.json()["grant_id"]


def test_diagnostics_are_read_only_site_limited_and_free_of_personal_data(client):
    h = setup(client)
    g = grant(client, h)
    o = client.post(f"/v1/platform/support-grants/{g}/open", headers=h)
    assert o.status_code == 200 and o.json()["mode"] == "read_only_diagnostics" and o.json()["tenant_id"] == "tenant_x"
    d = client.get(f"/v1/platform/support/{g}/diagnostics", headers=h).json()
    assert [s["site_id"] for s in d["sites"]] == ["s1"]                                            # only the granted site
    assert [r["site_id"] for r in d["rosters"]] == ["s1"] and d["workers_by_status"] == {"active": 1}
    assert "Secret Name" not in str(d) and "9999" not in str(d)
    assert client.post(f"/v1/platform/support/{g}/diagnostics", headers=h).status_code in (404, 405)   # no write verbs
    with client.session_local() as s:
        acts = [(e.action, e.actor_type, e.session_or_grant_ref) for e in s.scalars(select(SecurityAuditEvent).where(SecurityAuditEvent.action.like("support.%")))]
        op = s.scalar(select(PrivilegedSupportGrant)).operator_user_id
        assert ("support.session_open", "platform_admin", g) in acts and ("support.read", "platform_admin", g) in acts
        assert all(e.actor_id == op for e in s.scalars(select(SecurityAuditEvent).where(SecurityAuditEvent.action.in_(("support.read", "support.session_open")))))


def test_ended_expired_foreign_and_category_less_grants_fail_at_the_api(client):
    h = setup(client)
    g = grant(client, h)
    assert client.get(f"/v1/platform/support/{g}/diagnostics", headers=h).status_code == 200
    assert client.post(f"/v1/platform/support-grants/{g}/terminate", headers=h).status_code == 200
    ended = client.get(f"/v1/platform/support/{g}/diagnostics", headers=h)
    assert ended.status_code == 403 and "ended" in ended.json()["detail"]
    g2 = grant(client, h)
    with client.session_local() as s:
        x = s.get(PrivilegedSupportGrant, g2)
        x.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.commit()
    assert "expired" in client.get(f"/v1/platform/support/{g2}/diagnostics", headers=h).json()["detail"]
    g3 = grant(client, h, cats=("billing_view",))
    assert client.get(f"/v1/platform/support/{g3}/diagnostics", headers=h).status_code == 403
    g4 = grant(client, h)
    with client.session_local() as s:
        s.get(PrivilegedSupportGrant, g4).operator_user_id = s.get(PrivilegedSupportGrant, g3).approver_user_id   # same user in this one-admin setup: make it someone else
        from app.models.identity import TempoUser
        other = TempoUser(external_subject="idp|other", email="o@example.test")
        s.add(other)
        s.flush()
        s.get(PrivilegedSupportGrant, g4).operator_user_id = other.user_id
        s.commit()
    assert client.get(f"/v1/platform/support/{g4}/diagnostics", headers=h).status_code == 404       # someone else's grant
    assert client.get("/v1/platform/support/nope/diagnostics", headers=h).status_code == 404
