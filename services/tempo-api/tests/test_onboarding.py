"""Self-service onboarding — Phase F. Checks the property that makes this
model real rather than decorative: a connection can't be registered for a
site with no tenant scope (still requires the two-step order the API
enforces), and permission gates match §5.2 (labour.configure, Tenant
Admin) precisely.
"""
from __future__ import annotations

from .conftest import context_header


def _admin_header(**overrides):
    return context_header(roles=["tenant_admin"], **overrides)


def test_connector_catalogue_lists_all_four_connectors(client):
    response = client.get("/v1/connectors", headers=context_header())
    assert response.status_code == 200
    source_systems = {row["source_system"] for row in response.json()}
    assert source_systems == {"deputy", "ukg_pro_wfm", "ukg_ready", "wms"}


def test_connection_rejected_without_a_registered_tenant_scope(client):
    response = client.post(
        "/v1/connections", json={"source_system": "deputy", "site_id": "site_never_registered"}, headers=_admin_header()
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_tenant_scope_then_connection_succeeds(client):
    scope_resp = client.post("/v1/tenant-scopes", json={"site_id": "site_mel_01", "company_id": "cmp_1"}, headers=_admin_header())
    assert scope_resp.status_code == 201

    connection_resp = client.post(
        "/v1/connections", json={"source_system": "deputy", "site_id": "site_mel_01", "display_name": "Deputy AU"}, headers=_admin_header()
    )
    assert connection_resp.status_code == 201
    body = connection_resp.json()
    assert body["status"] == "pending_credentials", "no real vendor client exists — must never claim more than this"

    listed = client.get("/v1/connections", headers=_admin_header()).json()
    assert len(listed["connections"]) == 1
    assert listed["connections"][0]["connection_id"] == body["connection_id"]


def test_tenant_scope_creation_is_idempotent(client):
    first = client.post("/v1/tenant-scopes", json={"site_id": "site_mel_01"}, headers=_admin_header())
    second = client.post("/v1/tenant-scopes", json={"site_id": "site_mel_01"}, headers=_admin_header())
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()


def test_unknown_connector_source_system_rejected(client):
    client.post("/v1/tenant-scopes", json={"site_id": "site_mel_01"}, headers=_admin_header())
    response = client.post("/v1/connections", json={"source_system": "not_a_real_vendor", "site_id": "site_mel_01"}, headers=_admin_header())
    assert response.status_code == 422


def test_create_connection_requires_labour_configure(client):
    client.post("/v1/tenant-scopes", json={"site_id": "site_mel_01"}, headers=_admin_header())
    response = client.post(
        "/v1/connections", json={"source_system": "deputy", "site_id": "site_mel_01"}, headers=context_header(roles=["analyst"])
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "TEMPO-AUTH-002"
