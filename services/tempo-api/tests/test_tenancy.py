from .conftest import context_header


def test_unauthenticated_request_rejected(client):
    response = client.get("/v1/data-readiness", params={"capability": "optimize.roster"})
    assert response.status_code == 401
    assert response.json()["error_code"] == "TEMPO-AUTH-001"


def test_wide_open_tenant_scope_rejected(client):
    headers = context_header(site_ids=[], customer_ids=[])
    response = client.get("/v1/data-readiness", params={"capability": "optimize.roster"}, headers=headers)
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_legacy_context_header_is_not_authentication(client):
    response = client.get(
        "/v1/data-readiness",
        params={"capability": "optimize.roster"},
        headers={"X-Tempo-Context": "not json"},
    )
    assert response.status_code == 401


def test_valid_context_is_accepted(client):
    response = client.get(
        "/v1/data-readiness", params={"capability": "optimize.roster"}, headers=context_header()
    )
    assert response.status_code == 200
