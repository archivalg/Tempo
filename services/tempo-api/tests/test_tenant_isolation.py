"""Cross-tenant negative tests — SEC-03's "cross-tenant test suite" and the
tenant-isolation inventory's (docs/tenant-isolation-inventory.md) regression
baseline. Every test here proves *current* behaviour against the existing
X-Tempo-Context mechanism: tenant A must never reach tenant B's resources
by guessing/reusing an identifier, regardless of how the caller's identity
was established. This is a baseline to carry forward once Phase 1 replaces
the header with real token verification, not a substitute for it — a
caller who can set an arbitrary tenant_id in a forged header still defeats
every one of these checks, which is exactly why SEC-01/SEC-02 exist.

Also covers the regression this sprint's own audit found and fixed: five
call sites used `if context.site_ids and X not in context.site_ids`, which
skipped the check entirely when site_ids was empty instead of denying —
see docs/tenant-isolation-inventory.md §3.
"""
from __future__ import annotations

import uuid

from .conftest import context_header
from .test_run_endpoint import VALID_REQUEST, _headers, _seed

TENANT_A = "ten_test"  # matches _seed()'s hardcoded tenant
TENANT_B = "ten_isolation_other"
SITE_B = "site_syd_01"


def _headers_b(**overrides):
    return context_header(tenant_id=TENANT_B, site_ids=[SITE_B], customer_ids=["cust_B"], **overrides)


# --- Cross-tenant isolation -------------------------------------------------


def test_tenant_b_cannot_read_tenant_as_run(client):
    _seed(client)
    run_id = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers()).json()["run_id"]

    response = client.get(f"/v1/runs/{run_id}", headers=_headers_b())
    assert response.status_code == 404
    assert response.json()["error_code"] == "TEMPO-RUN-001"


def test_tenant_b_cannot_cancel_tenant_as_run(client):
    _seed(client)
    run_id = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers()).json()["run_id"]

    response = client.post(f"/v1/runs/{run_id}/cancel", headers=_headers_b())
    assert response.status_code == 404


def test_tenant_b_cannot_validate_an_action_against_tenant_as_recommendation(client):
    _seed(client)
    recommendation_id = client.post(
        "/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers()
    ).json()["recommendation_id"]

    response = client.post(
        "/v1/actions/validate",
        json={
            "action_type": "publish_roster",
            "recommendation_id": recommendation_id,
            "target": {"system": "deputy", "connection_id": "con_1", "site_id": SITE_B},
        },
        headers=_headers_b(),
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "TEMPO-ACTION-005"


def test_tenant_b_cannot_see_tenant_as_labour_provider(client):
    provider_id = client.post(
        "/v1/providers", json={"name": "Tenant A's Provider"}, headers=context_header(roles=["tenant_admin"])
    ).json()["provider_id"]

    response = client.get(
        f"/v1/providers/{provider_id}/workers",
        headers=context_header(tenant_id=TENANT_B, site_ids=[SITE_B], customer_ids=["cust_B"], roles=["tenant_admin"]),
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "TEMPO-PROVIDER-001"


def test_tenant_b_cannot_authenticate_a_worker_pin_enrolled_under_tenant_a(client):
    _seed(client)
    admin_headers = context_header(roles=["tenant_admin"])
    admin_headers["Idempotency-Key"] = str(uuid.uuid4())
    enroll = client.post("/v1/attendance/credentials", json={"worker_id": "wrk_0", "pin": "4242"}, headers=admin_headers)
    assert enroll.status_code == 201

    response = client.post(
        "/v1/attendance/whoami",
        json={"method": "pin", "pin": "4242"},
        headers=context_header(tenant_id=TENANT_B, site_ids=[SITE_B], roles=["operations_manager"]),
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "TEMPO-AUTH-001"


def test_tenant_scopes_and_connections_are_isolated_per_tenant(client):
    admin_a = context_header(roles=["tenant_admin"])
    admin_b = context_header(tenant_id=TENANT_B, site_ids=[SITE_B], customer_ids=["cust_B"], roles=["tenant_admin"])

    client.post("/v1/tenant-scopes", json={"site_id": "site_mel_01"}, headers=admin_a)
    client.post("/v1/tenant-scopes", json={"site_id": SITE_B}, headers=admin_b)

    scopes_a = client.get("/v1/tenant-scopes", headers=admin_a).json()
    scopes_b = client.get("/v1/tenant-scopes", headers=admin_b).json()

    assert {s["site_id"] for s in scopes_a} == {"site_mel_01"}
    assert {s["site_id"] for s in scopes_b} == {SITE_B}


# --- Empty site_ids must deny, never skip (docs/tenant-isolation-inventory.md §3) --


def _customer_only_headers(**overrides):
    # Legal under app/dependencies.py (only one of site_ids/customer_ids
    # needs to be non-empty) but must not grant unrestricted site access.
    return context_header(site_ids=[], customer_ids=["cust_A"], **overrides)


def test_run_creation_denies_when_caller_has_no_site_grant(client):
    _seed(client)
    idempotency_headers = _customer_only_headers(roles=["operations_manager"])
    idempotency_headers["Idempotency-Key"] = str(uuid.uuid4())

    response = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=idempotency_headers)
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_action_validate_denies_when_caller_has_no_site_grant(client):
    _seed(client)
    recommendation_id = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers()).json()[
        "recommendation_id"
    ]

    response = client.post(
        "/v1/actions/validate",
        json={
            "action_type": "publish_roster",
            "recommendation_id": recommendation_id,
            "target": {"system": "deputy", "connection_id": "con_1", "site_id": "site_mel_01"},
        },
        headers=_customer_only_headers(roles=["operations_manager"]),
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_clock_in_denies_when_caller_has_no_site_grant(client):
    _seed(client)
    response = client.post(
        "/v1/attendance/clock-in",
        json={"site_id": "site_mel_01", "method": "pin", "pin": "0000"},
        headers=_customer_only_headers(),
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_site_attendance_read_denies_when_caller_has_no_site_grant(client):
    _seed(client)
    response = client.get("/v1/sites/site_mel_01/attendance", headers=_customer_only_headers())
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_provider_worker_registration_denies_when_caller_has_no_site_grant(client):
    provider_id = client.post(
        "/v1/providers", json={"name": "Acme"}, headers=context_header(roles=["tenant_admin"])
    ).json()["provider_id"]

    response = client.post(
        f"/v1/providers/{provider_id}/workers",
        json={"home_site": "site_mel_01"},
        headers=_customer_only_headers(roles=["labour_provider"], provider_id=provider_id),
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"
