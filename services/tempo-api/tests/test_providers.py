"""Labour Provider — Business Spec §8's UX role. Checks the property that
makes the scoping real: a labour_provider caller can register/view/certify
workers under its own provider_id, never another provider's, while a
Tenant Admin (labour.configure) can reach any provider in the tenant.
"""
from __future__ import annotations

from .conftest import context_header


def _admin_header(**overrides):
    return context_header(roles=["tenant_admin"], **overrides)


def _provider_header(provider_id: str, **overrides):
    return context_header(roles=["labour_provider"], provider_id=provider_id, **overrides)


def _create_provider(client, name: str = "Acme Labour Hire") -> str:
    response = client.post("/v1/providers", json={"name": name}, headers=_admin_header())
    assert response.status_code == 201, response.text
    return response.json()["provider_id"]


def test_tenant_admin_registers_a_provider(client):
    response = client.post("/v1/providers", json={"name": "Acme Labour Hire"}, headers=_admin_header())
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Labour Hire"
    assert body["status"] == "active"

    listed = client.get("/v1/providers", headers=_admin_header())
    assert listed.status_code == 200
    assert any(p["provider_id"] == body["provider_id"] for p in listed.json())


def test_registering_a_provider_requires_labour_configure(client):
    response = client.post("/v1/providers", json={"name": "Acme Labour Hire"}, headers=context_header(roles=["operations_manager"]))
    assert response.status_code == 403


def test_labour_provider_registers_and_lists_own_supplied_worker(client):
    provider_id = _create_provider(client)
    response = client.post(
        f"/v1/providers/{provider_id}/workers",
        json={"home_site": "site_mel_01"},
        headers=_provider_header(provider_id),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["provider_id"] == provider_id
    assert body["employment_type"] == "labour_hire"
    assert body["certifications"] == []
    assert body["upcoming_shifts"] == []

    listed = client.get(f"/v1/providers/{provider_id}/workers", headers=_provider_header(provider_id))
    assert listed.status_code == 200
    assert [w["worker_id"] for w in listed.json()] == [body["worker_id"]]


def test_labour_provider_cannot_reach_another_providers_workers(client):
    own_provider_id = _create_provider(client, "Acme Labour Hire")
    other_provider_id = _create_provider(client, "Beta Staffing")
    client.post(f"/v1/providers/{other_provider_id}/workers", json={"home_site": "site_mel_01"}, headers=_admin_header())

    response = client.get(f"/v1/providers/{other_provider_id}/workers", headers=_provider_header(own_provider_id))
    assert response.status_code == 403

    register_response = client.post(
        f"/v1/providers/{other_provider_id}/workers", json={"home_site": "site_mel_01"}, headers=_provider_header(own_provider_id)
    )
    assert register_response.status_code == 403


def test_tenant_admin_can_manage_any_provider(client):
    provider_id = _create_provider(client)
    response = client.post(f"/v1/providers/{provider_id}/workers", json={"home_site": "site_mel_01"}, headers=_admin_header())
    assert response.status_code == 201


def test_registering_a_worker_outside_caller_site_scope_is_rejected(client):
    provider_id = _create_provider(client)
    response = client.post(
        f"/v1/providers/{provider_id}/workers",
        json={"home_site": "site_never_registered"},
        headers=_provider_header(provider_id),
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_labour_provider_adds_a_certification_for_its_own_worker(client):
    provider_id = _create_provider(client)
    worker_id = client.post(
        f"/v1/providers/{provider_id}/workers", json={"home_site": "site_mel_01"}, headers=_provider_header(provider_id)
    ).json()["worker_id"]

    response = client.post(
        f"/v1/providers/{provider_id}/workers/{worker_id}/certifications",
        json={"skill_code": "forklift_lo", "valid_from": "2026-01-01T00:00:00Z"},
        headers=_provider_header(provider_id),
    )
    assert response.status_code == 201, response.text
    assert response.json()["skill_code"] == "forklift_lo"

    listed = client.get(f"/v1/providers/{provider_id}/workers", headers=_provider_header(provider_id))
    assert listed.json()[0]["certifications"][0]["skill_code"] == "forklift_lo"


def test_labour_provider_cannot_certify_a_worker_it_does_not_supply(client):
    provider_id = _create_provider(client, "Acme Labour Hire")
    other_provider_id = _create_provider(client, "Beta Staffing")
    other_worker_id = client.post(
        f"/v1/providers/{other_provider_id}/workers", json={"home_site": "site_mel_01"}, headers=_admin_header()
    ).json()["worker_id"]

    # The path's own provider_id (provider_id) matches the caller, so this
    # clears the access check — it 404s instead, because the worker
    # belongs to a different provider than the one named in the path.
    response = client.post(
        f"/v1/providers/{provider_id}/workers/{other_worker_id}/certifications",
        json={"skill_code": "forklift_lo", "valid_from": "2026-01-01T00:00:00Z"},
        headers=_provider_header(provider_id),
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "TEMPO-PROVIDER-001"


def test_provider_not_found_is_404(client):
    response = client.get("/v1/providers/prov_nonexistent/workers", headers=_provider_header("prov_nonexistent"))
    assert response.status_code == 404
    assert response.json()["error_code"] == "TEMPO-PROVIDER-001"
