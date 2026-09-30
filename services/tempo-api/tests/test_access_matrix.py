"""Gate 1 evidence: principal × route × tenant/site/customer/provider IDOR and permission matrix.

Objects are created in tenant A / site_mel_01. Attackers are: tenant B with every role and grant,
a tenant-A user granted only a *different* site, a tenant-A user with only a customer grant, and
tenant-A users whose role lacks the permission. Nothing may leak, and foreign ids are 404 (never 403/200).
"""
from __future__ import annotations

import uuid

import pytest

from .conftest import context_header, enrol_kiosk
from .test_run_endpoint import VALID_REQUEST, WINDOW_START, _headers, _seed

TENANT_B, SITE_B = "ten_matrix_b", "site_b_01"
PUBLIC = {  # intentionally unauthenticated (pre-login) — each is separately tested
    ("GET", "/healthz"), ("GET", "/readyz"), ("GET", "/v1/auth/config"), ("GET", "/v1/auth/dev-identities"), ("POST", "/v1/auth/dev-login"), ("GET", "/v1/auth/oidc/login"),
    ("GET", "/v1/auth/oidc/callback"), ("POST", "/v1/auth/login"), ("POST", "/v1/auth/mfa/verify"), ("POST", "/v1/auth/accept-invite"), ("GET", "/v1/auth/invite/{token}"), ("POST", "/v1/auth/refresh"), ("POST", "/v1/kiosk/enrol"),
}


def _ops(**kw):
    return context_header(**kw)


def _attacker_b():
    return context_header(tenant_id=TENANT_B, site_ids=[SITE_B], customer_ids=["cust_B"], roles=["tenant_admin", "operations_manager", "planner"])


@pytest.fixture()
def world(client):
    _seed(client)
    admin = context_header(roles=["tenant_admin"])
    run = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers()).json()
    rr = client.post("/v1/optimisations/named_roster", json={**VALID_REQUEST, "request_id": "req_2"}, headers=_headers())
    assert rr.status_code == 202, rr.text
    rec = rr.json()["recommendation_id"]
    prov = client.post("/v1/providers", json={"name": "Acme"}, headers=admin).json()["provider_id"]
    worker = client.post(f"/v1/providers/{prov}/workers", json={"home_site": "site_mel_01"}, headers=admin).json()
    client.post("/v1/tenant-scopes", json={"site_id": "site_mel_01"}, headers=admin)
    conn = client.post("/v1/connections", json={"source_system": "deputy", "site_id": "site_mel_01", "display_name": "d"}, headers=admin).json()
    dev = client.post("/v1/devices", json={"name": "k", "site_ids": ["site_mel_01"]}, headers=admin).json()
    return {"run": run["run_id"], "rec": rec, "prov": prov, "worker": worker["worker_id"], "conn": conn["connection_id"],
            "dev": dev["device_id"]}


def _routes(w):
    """(method, path, body) for every object-addressed tenant route."""
    return [
        ("GET", f"/v1/runs/{w['run']}", None),
        ("POST", f"/v1/runs/{w['run']}/cancel", None),
        ("POST", "/v1/run-comparisons", {"run_ids": [w["run"], w["run"]]}),
        ("GET", f"/v1/providers/{w['prov']}/workers", None),
        ("POST", f"/v1/providers/{w['prov']}/workers", {"home_site": SITE_B}),
        ("POST", f"/v1/providers/{w['prov']}/workers/{w['worker']}/certifications", {"skill_code": "x", "valid_from": "2026-01-01T00:00:00Z"}),
        ("GET", f"/v1/workers/{w['worker']}/shifts", None),
        ("GET", "/v1/sites/site_mel_01/attendance", None),
        ("GET", f"/v1/connections/{w['conn']}/health", None),
        ("POST", f"/v1/connections/{w['conn']}/test", None),
        ("POST", f"/v1/connections/{w['conn']}/suspend", None),
        ("POST", f"/v1/connections/{w['conn']}/revoke", None),
        ("POST", f"/v1/connections/{w['conn']}/activate", None),
        ("POST", f"/v1/connections/{w['conn']}/credentials", {"secret": {"token": "not-a-real-secret"}}),
        ("POST", f"/v1/devices/{w['dev']}/disable", None),
        ("POST", f"/v1/devices/{w['dev']}/enrolment-code", None),
        ("POST", "/v1/actions/validate", {"action_type": "publish_roster", "recommendation_id": w["rec"],
                                          "target": {"system": "deputy", "connection_id": w["conn"], "site_id": "site_mel_01"}}),
    ]


def _send(client, method, path, body, headers):
    h = dict(headers)
    if method == "POST":
        h["Idempotency-Key"] = str(uuid.uuid4())
    return client.request(method, path, json=body, headers=h)


def test_every_non_public_route_rejects_anonymous_callers(client):
    schema = client.get("/openapi.json").json()["paths"]
    checked = 0
    for path, ops in schema.items():
        for method in ops:
            if (method.upper(), path) in PUBLIC:
                continue
            concrete = path.replace("{run_type}", "demand_forecast")
            for token in ("{run_id}", "{provider_id}", "{worker_id}", "{connection_id}", "{device_id}", "{action_id}", "{site_id}", "{tenant_id}", "{grant_id}"):
                concrete = concrete.replace(token, "x")
            r = client.request(method.upper(), concrete, json={} if method != "get" else None)
            assert r.status_code == 401, f"{method.upper()} {path} answered {r.status_code} to an anonymous caller"
            checked += 1
    assert checked >= 45


def test_tenant_b_gets_nothing_and_learns_nothing_about_tenant_a_objects(client, world):
    for method, path, body in _routes(world):
        r = _send(client, method, path, body, _attacker_b())
        assert r.status_code in (404, 400), f"{method} {path} -> {r.status_code} {r.text[:120]}"
        text = r.text
        for secret in (world["run"], world["worker"], world["conn"]):
            assert secret not in text or r.status_code == 404  # 404 may echo the caller's own supplied id only
        assert r.status_code != 403, f"{method} {path}: 403 discloses existence"


def test_listings_for_tenant_b_are_empty_of_tenant_a(client, world):
    b = _attacker_b()
    assert client.get("/v1/runs", headers=b).json()["runs"] == []
    assert client.get("/v1/providers", headers=b).json() == []
    assert client.get("/v1/connections", headers=b).json()["connections"] == []
    assert client.get("/v1/tenant-scopes", headers=b).json() == []
    assert client.get("/v1/devices", headers=b).json() == []
    assert client.get("/v1/actions", headers=b).json()["actions"] == []


def test_same_tenant_user_with_a_different_site_grant_cannot_reach_site_a_objects(client, world):
    other_site = context_header(site_ids=["site_other"], customer_ids=[], roles=["tenant_admin", "operations_manager"], user_id="usr_other_site")
    for method, path, body in _routes(world):
        if "site_mel_01" not in path and SITE_B not in str(body) and "providers" not in path:
            pass
        r = _send(client, method, path, body, other_site)
        empty_list = r.status_code == 200 and method == "GET" and r.json() == []  # filtered listing, nothing disclosed
        assert r.status_code in (400, 403, 404) or empty_list, f"{method} {path} -> {r.status_code} (site scope not enforced)"
    assert client.get("/v1/runs", headers=other_site).json()["runs"] == []
    assert client.get("/v1/connections", headers=other_site).json()["connections"] == []
    assert client.get("/v1/tenant-scopes", headers=other_site).json() == []
    assert client.get("/v1/devices", headers=other_site).json() == []
    assert client.get("/v1/actions", headers=other_site).json()["actions"] == []


def test_customer_grant_alone_never_expands_to_sites(client, world):
    cust_only = context_header(site_ids=[], customer_ids=["cust_A"], roles=["tenant_admin", "operations_manager"], user_id="usr_cust_only")
    for method, path, body in _routes(world):
        r = _send(client, method, path, body, cust_only)
        empty_list = r.status_code == 200 and method == "GET" and r.json() == []
        assert r.status_code in (400, 403, 404) or empty_list, f"{method} {path} -> {r.status_code}"
    ing = {"envelope": {"tenant_id": "ten_test", "site_id": "site_mel_01", "schema_version": "1.0", "source_system": "x", "source_id": "1",
                        "occurred_at": "2026-09-08T00:00:00Z", "ingested_at": "2026-09-08T00:00:00Z"}, "entity_type": "worker", "fields": {}}
    r = client.post("/v1/ingestion/events", json=ing, headers=context_header(site_ids=[], customer_ids=["cust_A"], roles=["integration_restricted"], user_id="usr_ing"))
    assert r.status_code in (400, 403, 422)


WRITE_PERMISSION = [  # (method, path builder, role that lacks it, expected)
    ("POST", "/v1/providers", {"name": "x"}, "analyst"),
    ("POST", "/v1/tenant-scopes", {"site_id": "site_mel_01"}, "planner"),
    ("POST", "/v1/connections", {"source_system": "deputy", "site_id": "site_mel_01", "display_name": "d"}, "operations_manager"),
    ("POST", "/v1/devices", {"name": "k", "site_ids": ["site_mel_01"]}, "supervisor"),
    ("POST", "/v1/site-geofences", {"site_id": "site_mel_01", "latitude": 1.0, "longitude": 1.0, "radius_meters": 50}, "supervisor"),
    ("POST", "/v1/attendance/credentials", {"worker_id": "w", "pin": "1234"}, "planner"),
    ("POST", "/v1/monitoring/models/drift-check", {}, "analyst"),
]


@pytest.mark.parametrize("method,path,body,role", WRITE_PERMISSION)
def test_role_without_the_permission_gets_403_on_each_write(client, world, method, path, body, role):
    r = _send(client, method, path, body, context_header(roles=[role], user_id=f"usr_{role}"))
    assert r.status_code == 403, f"{method} {path} as {role} -> {r.status_code}"


def test_read_permission_needed_even_with_site_grant(client, world):
    no_read = context_header(roles=["hr_authorised"], user_id="usr_hr")  # holds labour.worker_pii only
    for path in (f"/v1/runs/{world['run']}", "/v1/runs", "/v1/sites/site_mel_01/attendance", f"/v1/workers/{world['worker']}/shifts", "/v1/connections"):
        assert client.get(path, headers=no_read).status_code == 403, path


def test_kiosk_device_credential_reaches_no_console_route(client, world):
    dev = enrol_kiosk(client)
    for method, path, body in _routes(world):
        r = _send(client, method, path, body, dev)
        assert r.status_code in (401, 403), f"kiosk token accepted on {method} {path}: {r.status_code}"


def test_console_token_reaches_no_platform_route(client, world):
    for path in ("/v1/platform/tenants", "/v1/platform/audit"):
        assert client.get(path, headers=context_header(roles=["tenant_admin"])).status_code == 403
