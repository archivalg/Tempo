"""Roadmap M6-PLAN / M6-MANUAL / M6-ADMIN: versioned plans, manual (non-Stripe) subscriptions, allowances, entitlement limits, platform overview."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models.billing import PlanDefinition, SubscriptionEvent, TenantSubscription
from app.models.canonical import Worker

from .conftest import context_header
from .test_platform import _admin_headers, _bootstrap


@pytest.fixture(autouse=True)
def _http_cookies(monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", False)


@pytest.fixture(autouse=True)
def _plans(client):
    """The migration seeds the indicative catalogue; the per-test truncate removes it, so restore the same rows."""
    from app.models.billing import DEFAULT_PLANS
    with client.session_local() as s:
        for k, n, price in DEFAULT_PLANS:
            s.add(PlanDefinition(id=f"plan-{k}-1", plan_key=k, version=1, name=n, monthly_price_per_site_aud=price, entitlements={}, status="draft"))
        s.commit()


def sub_body(**kw):
    return {"plan_key": "optimise", "licensed_sites": 2, "worker_band": "250", "manual_kind": "pilot", "reason": "Pilot agreed with the customer owner", "reference": "PILOT-001", **kw}


def make_tenant(client, h, tid="acme", **sub):
    r = client.post("/v1/platform/tenants", headers=h, json={"tenant_id": tid, "name": "Acme Logistics", "first_admin": {"email": f"{tid}@example.test"}, "initial_site_ids": ["s1"],
                                                            "subscription": sub_body(**sub)})
    assert r.status_code == 201, r.text
    return r.json()


def test_plan_catalogue_is_seeded_as_unapproved_drafts_and_approval_is_a_deliberate_step(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    plans = {p["plan_key"]: p for p in client.get("/v1/platform/plans", headers=h).json()}
    assert set(plans) == {"essentials", "optimise", "orchestrate", "network"}
    assert all(p["status"] == "draft" and p["indicative"] for p in plans.values())
    assert plans["optimise"]["monthly_price_per_site_aud"] == 3500 and plans["network"]["monthly_price_per_site_aud"] is None and plans["optimise"]["entitlements"] == {}
    v2 = client.post("/v1/platform/plans", headers=h, json={"plan_key": "optimise", "name": "Optimise", "monthly_price_per_site_aud": 3400, "notes": "negotiated"}).json()
    assert v2["version"] == 2 and v2["status"] == "draft"
    ok = client.post(f"/v1/platform/plans/{v2['id']}/approve", headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "approved" and ok.json()["approved_by"]
    assert client.post(f"/v1/platform/plans/{v2['id']}/approve", headers=h).status_code == 422
    with client.session_local() as s:
        with pytest.raises(Exception):   # approved definitions are never deleted by the app role
            with client.app_session_local() as a:
                a.execute(text("DELETE FROM plan_definition"))
                a.commit()


def test_manual_tenant_is_provisioned_without_stripe_and_the_customer_sees_their_allowance(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    t = make_tenant(client, h)
    assert t["invite_token"]                                            # first admin can set a password; no payment card, no checkout
    with client.session_local() as s:
        row = s.get(TenantSubscription, "acme")
        assert row.billing_source == "manual" and row.stripe_customer_id is None and row.stripe_subscription_id is None
        assert row.plan_key == "optimise" and row.plan_version == 1 and row.manual_kind == "pilot"
        with pytest.raises(IntegrityError):                              # the database refuses a manual row that carries Stripe IDs
            row.stripe_subscription_id = "sub_fabricated"
            s.commit()
        s.rollback()
        assert [e.action for e in s.scalars(select(SubscriptionEvent))] == ["created"]
    me = context_header(tenant_id="acme", site_ids=["s1"], roles=["tenant_admin"], user_id="usr_acme")
    plan = client.get("/v1/billing/plan", headers=me).json()
    assert plan["managed"] and plan["plan"]["name"] == "Optimise" and plan["plan"]["approved"] is False and plan["billing_source"] == "manual"
    assert plan["licensed_sites"] == 2 and plan["worker_allowance"] == 250 and plan["allowance_state"] == "ok" and "counted once" in plan["measurement"]


def test_draft_plans_are_only_for_pilots_and_demos_and_stripe_is_refused_not_faked(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    r = client.post("/v1/platform/tenants", headers=h, json={"tenant_id": "paid_co", "name": "Paid Co", "first_admin": {"email": "p@example.test"}, "initial_site_ids": ["s1"],
                                                            "subscription": sub_body(manual_kind="contract")})
    assert r.status_code == 422 and "no approved version" in r.json()["detail"]
    bad = client.post("/v1/platform/tenants", headers=h, json={"tenant_id": "stripe_co", "name": "Stripe Co", "first_admin": {"email": "s@example.test"}, "initial_site_ids": ["s1"],
                                                              "subscription": sub_body(billing_source="stripe")})
    assert bad.status_code == 400 and "Stripe billing is not connected" in bad.json()["detail"]
    few = client.post("/v1/platform/tenants", headers=h, json={"tenant_id": "few_co", "name": "Few Co", "first_admin": {"email": "f@example.test"}, "initial_site_ids": ["a", "b", "c"],
                                                              "subscription": sub_body(licensed_sites=1)})
    assert few.status_code == 400
    with client.session_local() as s:
        assert s.scalars(select(TenantSubscription)).all() == []        # nothing half-created


def test_allowance_warns_but_never_blocks_and_the_site_limit_is_the_only_hard_one(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    make_tenant(client, h, licensed_sites=1, worker_band="250")
    me = context_header(tenant_id="acme", site_ids=["s1"], roles=["tenant_admin"], user_id="usr_acme")
    from app.models.directory import Site
    with client.session_local() as s:
        s.add(Site(tenant_id="acme", site_id="s1", name="One", timezone="Australia/Melbourne"))
        for i in range(226):
            s.add(Worker(worker_id=f"w{i}", tenant_id="acme", employment_type="casual" if i % 2 else "labour_hire", home_site="s1", status="active"))
        s.add(Worker(worker_id="gone", tenant_id="acme", employment_type="casual", home_site="s1", status="inactive"))
        s.commit()
    p = client.get("/v1/billing/plan", headers=me).json()
    assert p["active_workers"] == 226 and p["allowance_state"] == "near" and "close to" in p["allowance_message"]    # inactive not counted; agency counted
    with client.session_local() as s:
        for i in range(226, 300):
            s.add(Worker(worker_id=f"w{i}", tenant_id="acme", employment_type="casual", home_site="s1", status="active"))
        s.commit()
    p = client.get("/v1/billing/plan", headers=me).json()
    assert p["allowance_state"] == "over" and "Nothing has been blocked" in p["allowance_message"]
    # a second site is refused with a route to ask for more, because the plan covers one
    import csv, io, json
    head, row = ["site_id", "name", "timezone", "operating_mode"], ["s2", "Second", "Australia/Sydney", ""]
    buf = io.StringIO(); w = csv.writer(buf, lineterminator="\n"); w.writerow(head); w.writerow(row)
    q = {"data_class": "master", "entity": "sites"}
    hdr = {**me, "Content-Type": "text/csv"}
    ins = client.post("/v1/imports/csv/inspect", params=q, content=buf.getvalue().encode(), headers=hdr).json()
    b = client.post("/v1/imports/csv/stage", params={**q, "mapping": json.dumps(ins["suggested_mapping"])}, content=buf.getvalue().encode(), headers=hdr).json()
    r = client.post(f"/v1/imports/batches/{b['id']}/apply", headers=me)
    assert r.status_code == 422 and "Contact us to add sites" in r.json()["detail"]


def test_changing_and_suspending_a_manual_tenant_is_recorded_and_survives_unrelated_updates(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    make_tenant(client, h)
    ch = client.put("/v1/platform/tenants/acme/subscription", headers=h, json=sub_body(licensed_sites=3, worker_band="500", reason="Customer added a site", manual_kind="pilot"))
    assert ch.status_code == 200 and ch.json()["licensed_sites"] == 3 and ch.json()["worker_band"] == "500"
    assert client.put("/v1/platform/tenants/acme/subscription", headers=h, json=sub_body(licensed_sites=0)).status_code == 422
    assert client.post("/v1/platform/tenants/acme/status?status=suspended", headers=h).status_code == 200
    assert client.post("/v1/platform/tenants/acme/status?status=active", headers=h).status_code == 200
    with client.session_local() as s:
        acts = [e.action for e in s.scalars(select(SubscriptionEvent).order_by(SubscriptionEvent.at))]
        assert acts == ["created", "changed", "tenant_suspended", "tenant_active"]
        changed = s.scalars(select(SubscriptionEvent).where(SubscriptionEvent.action == "changed")).one()
        assert changed.detail["before"]["licensed_sites"] == 2 and changed.reason == "Customer added a site"
        row = s.get(TenantSubscription, "acme")
        assert row.billing_source == "manual" and row.licensed_sites == 3
    me = context_header(tenant_id="acme", site_ids=["s1"], roles=["tenant_admin"], user_id="usr_acme")
    assert [e["action"] for e in client.get("/v1/billing/plan", headers=me).json()["history"]][0] == "tenant_active"


def test_expiry_is_visible_and_platform_overview_is_searchable_counts_only(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    make_tenant(client, h, expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    make_tenant(client, h, tid="zeta", manual_kind="demo")
    me = context_header(tenant_id="acme", site_ids=["s1"], roles=["tenant_admin"], user_id="usr_acme")
    assert client.get("/v1/billing/plan", headers=me).json()["status"] == "expired"
    allrows = client.get("/v1/platform/tenant-overview", headers=h).json()
    assert {r["tenant_id"] for r in allrows} == {"acme", "zeta"}
    one = client.get("/v1/platform/tenant-overview", params={"q": "zet"}, headers=h).json()
    assert [r["tenant_id"] for r in one] == ["zeta"] and one[0]["billing_source"] == "manual" and one[0]["manual_kind"] == "demo"
    assert set(one[0]) >= {"plan", "licensed_sites", "sites_in_use", "worker_band", "active_workers", "allowance_state", "subscription_status"}
    assert client.get("/v1/platform/tenant-overview", headers=me).status_code == 403          # tenant users cannot see other tenants
    unmanaged = client.get("/v1/billing/plan", headers=context_header(roles=["analyst"], user_id="usr_an")).json()
    assert unmanaged["managed"] is False and "no commercial limits" in unmanaged["message"]


def test_console_cookie_session_reaches_platform_routes_only_with_csrf_and_a_platform_admin(client):
    _bootstrap(subject="idp|admin", email=None)
    r = client.post("/v1/auth/dev-login", json={"subject": "idp|admin", "email": "admin@example.test", "mfa": True})
    assert r.status_code == 200
    csrf = client.cookies.get("tempo_csrf")
    assert client.get("/v1/platform/plans").status_code == 200                                    # cookie session, read
    body = {"plan_key": "optimise", "name": "Optimise", "monthly_price_per_site_aud": 3400}
    assert client.post("/v1/platform/plans", json=body).status_code == 403                       # change without the CSRF token
    assert client.post("/v1/platform/plans", json=body, headers={"X-CSRF-Token": csrf}).status_code == 201
    assert client.get("/v1/platform/support-grants").json() == []
    client.cookies.clear()
    # a tenant user's cookie session is not a platform session
    client.post("/v1/auth/dev-login", json={"subject": "idp|plain", "email": "plain@example.test", "mfa": True})
    assert client.get("/v1/platform/plans").status_code in (401, 403)


def test_a_platform_admin_can_invite_another_administrator_into_a_tenant(client):
    _bootstrap(subject="idp|admin", email=None)
    h = _admin_headers(client)
    make_tenant(client, h)
    r = client.post("/v1/platform/tenants/acme/admins", json={"email": "second.admin@example.test"}, headers=h)
    assert r.status_code == 201, r.text
    assert r.json()["sites"] == ["s1"] and r.json()["invite_token"]
    with client.session_local() as s:
        from app.models.identity import TempoUser, UserRoleAssignment
        u = s.scalar(select(TempoUser).where(TempoUser.email == "second.admin@example.test"))
        assert [x.role for x in s.scalars(select(UserRoleAssignment).where(UserRoleAssignment.user_id == u.user_id))] == ["tenant_admin"]
    again = client.post("/v1/platform/tenants/acme/admins", json={"email": "second.admin@example.test"}, headers=h)          # a repeat re-issues the link; no duplicate role
    assert again.status_code == 201 and again.json()["invite_token"] != r.json()["invite_token"]
    assert client.post("/v1/platform/tenants/nope/admins", json={"email": "x@example.test"}, headers=h).status_code == 404
    assert client.post("/v1/platform/tenants/acme/admins", json={"email": "not-an-email"}, headers=h).status_code == 422
    me = context_header(tenant_id="acme", site_ids=["s1"], roles=["tenant_admin"], user_id="usr_acme")
    assert client.post("/v1/platform/tenants/acme/admins", json={"email": "z@example.test"}, headers=me).status_code in (401, 403)   # a tenant admin cannot use platform routes
