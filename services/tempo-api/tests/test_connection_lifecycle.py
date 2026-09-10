"""INT-03/INT-04: connector credential lifecycle. Checks the property that
makes this real rather than decorative: a connection can't activate
without a stored credential, test/activate never leak or fabricate a live
vendor result (app/maestro/credentials.py has no real vendor endpoint to
call), and revoke is both terminal and idempotent.
"""
from __future__ import annotations

from .conftest import context_header


def _admin_header(**overrides):
    return context_header(roles=["tenant_admin"], **overrides)


def _register_connection(client) -> str:
    client.post("/v1/tenant-scopes", json={"site_id": "site_mel_01"}, headers=_admin_header())
    response = client.post(
        "/v1/connections", json={"source_system": "deputy", "site_id": "site_mel_01"}, headers=_admin_header()
    )
    assert response.status_code == 201
    return response.json()["connection_id"]


def test_connection_starts_pending_credentials(client):
    connection_id = _register_connection(client)
    listed = client.get("/v1/connections", headers=_admin_header()).json()["connections"]
    assert next(c for c in listed if c["connection_id"] == connection_id)["status"] == "pending_credentials"


def test_activate_without_stored_credentials_is_rejected(client):
    connection_id = _register_connection(client)
    response = client.post(f"/v1/connections/{connection_id}/activate", headers=_admin_header())
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_full_lifecycle_store_test_activate_suspend_revoke(client):
    connection_id = _register_connection(client)

    store_response = client.post(
        f"/v1/connections/{connection_id}/credentials",
        json={"secret": {"api_key": "not-a-real-key"}},
        headers=_admin_header(),
    )
    assert store_response.status_code == 201
    assert store_response.json()["status"] == "credentials_stored"

    test_response = client.post(f"/v1/connections/{connection_id}/test", headers=_admin_header())
    assert test_response.status_code == 200
    test_body = test_response.json()
    assert test_body["ok"] is True
    # Must never claim a live vendor was actually contacted -- no real
    # vendor client exists for any catalogued source_system.
    assert "no live vendor endpoint" in test_body["detail"]
    assert "api_key" not in test_response.text
    assert "not-a-real-key" not in test_response.text

    activate_response = client.post(f"/v1/connections/{connection_id}/activate", headers=_admin_header())
    assert activate_response.status_code == 200
    assert activate_response.json()["status"] == "active"

    suspend_response = client.post(f"/v1/connections/{connection_id}/suspend", headers=_admin_header())
    assert suspend_response.status_code == 200
    assert suspend_response.json()["status"] == "suspended"

    # Reversible: a suspended connection can be re-activated.
    reactivate_response = client.post(f"/v1/connections/{connection_id}/activate", headers=_admin_header())
    assert reactivate_response.status_code == 200
    assert reactivate_response.json()["status"] == "active"

    revoke_response = client.post(f"/v1/connections/{connection_id}/revoke", headers=_admin_header())
    assert revoke_response.status_code == 200
    assert revoke_response.json()["status"] == "revoked"

    # Idempotent.
    second_revoke = client.post(f"/v1/connections/{connection_id}/revoke", headers=_admin_header())
    assert second_revoke.status_code == 200
    assert second_revoke.json()["status"] == "revoked"

    # Terminal: revoking clears the credential, so re-activation is
    # rejected exactly like it never had one.
    reactivate_after_revoke = client.post(f"/v1/connections/{connection_id}/activate", headers=_admin_header())
    assert reactivate_after_revoke.status_code == 400


def test_revoked_connection_cannot_accept_new_credentials(client):
    connection_id = _register_connection(client)
    client.post(
        f"/v1/connections/{connection_id}/credentials", json={"secret": {"api_key": "k"}}, headers=_admin_header()
    )
    client.post(f"/v1/connections/{connection_id}/revoke", headers=_admin_header())

    response = client.post(
        f"/v1/connections/{connection_id}/credentials", json={"secret": {"api_key": "k2"}}, headers=_admin_header()
    )
    assert response.status_code == 400


def test_credential_lifecycle_requires_labour_configure(client):
    connection_id = _register_connection(client)
    plain_header = context_header(roles=["operations_manager"])
    response = client.post(
        f"/v1/connections/{connection_id}/credentials", json={"secret": {"api_key": "k"}}, headers=plain_header
    )
    assert response.status_code == 403


def test_test_endpoint_reports_missing_credentials_honestly(client):
    connection_id = _register_connection(client)
    response = client.post(f"/v1/connections/{connection_id}/test", headers=_admin_header())
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "no credentials stored" in body["detail"]
