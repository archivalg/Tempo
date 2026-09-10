"""INT-11: connection health. A freshly registered connection has never
actually synced (no real vendor sandbox exists to sync against -- see
INT-05/INT-06's own disclosed gap), so its health must honestly report
empty, not fabricate activity. Once a checkpoint/dead-letter row exists
(written directly here, the same way a real connector's own ingestion
loop eventually would), health reflects it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.connectors import ConnectorCheckpoint, IngestionDeadLetter

from .conftest import context_header


def _admin_header(**overrides):
    return context_header(roles=["tenant_admin"], **overrides)


def _register_connection(client) -> str:
    client.post("/v1/tenant-scopes", json={"site_id": "site_mel_01"}, headers=_admin_header())
    return client.post(
        "/v1/connections", json={"source_system": "deputy", "site_id": "site_mel_01"}, headers=_admin_header()
    ).json()["connection_id"]


def test_health_is_honestly_empty_for_a_never_synced_connection(client):
    connection_id = _register_connection(client)
    response = client.get(f"/v1/connections/{connection_id}/health", headers=_admin_header())
    assert response.status_code == 200
    body = response.json()
    assert body["checkpoints"] == []
    assert body["last_successful_sync"] is None
    assert body["lag_seconds"] is None
    assert body["dead_letters_unresolved"] == 0
    assert body["dead_letters_total"] == 0


def test_health_reflects_real_checkpoint_and_dead_letter_rows(client):
    connection_id = _register_connection(client)
    now = datetime.now(timezone.utc)

    with client.session_local() as session:
        session.add(
            ConnectorCheckpoint(
                tenant_id="ten_test", connection_id=connection_id, entity_type="employees",
                watermark="2026-01-01T00:00:00Z", updated_at=now - timedelta(minutes=10),
            )
        )
        session.add(
            IngestionDeadLetter(
                tenant_id="ten_test", source_system="deputy", connection_id=connection_id, entity_type="employees",
                event_id="evt_1", quality_status="quarantined", reason="missing required field",
                raw_envelope={"bad": "data"}, resolved=False,
            )
        )
        session.add(
            IngestionDeadLetter(
                tenant_id="ten_test", source_system="deputy", connection_id=connection_id, entity_type="employees",
                event_id="evt_2", quality_status="quarantined", reason="resolved already",
                raw_envelope={"bad": "data"}, resolved=True,
            )
        )
        session.commit()

    response = client.get(f"/v1/connections/{connection_id}/health", headers=_admin_header())
    body = response.json()
    assert body["checkpoints"] == [{"entity_type": "employees", "watermark": "2026-01-01T00:00:00Z", "updated_at": body["checkpoints"][0]["updated_at"]}]
    assert body["last_successful_sync"] is not None
    assert 590 < body["lag_seconds"] < 700  # ~10 minutes, generous bound for test timing
    assert body["dead_letters_unresolved"] == 1
    assert body["dead_letters_total"] == 2


def test_health_requires_labour_read(client):
    connection_id = _register_connection(client)
    response = client.get(
        f"/v1/connections/{connection_id}/health", headers=context_header(roles=["integration_restricted"])
    )
    assert response.status_code == 403
