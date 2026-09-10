"""INT-02: the canonical ingestion API. Checks the property that makes it
a real contract rather than a passthrough: tenant binding and schema
version are validated before anything touches the canonical store, and
resubmitting the same envelope upserts the same row rather than creating a
duplicate (the same idempotency guarantee every connector already relies
on via app.core.ingestion.apply_canonical_envelope, now reachable over
HTTP for the first time).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models.canonical import Worker

from .conftest import context_header


def _integration_header(**overrides):
    return context_header(roles=["integration_restricted"], **overrides)


def _worker_envelope(**overrides):
    now = datetime.now(timezone.utc).isoformat()
    envelope = {
        "schema_version": "1.0",
        "event_id": f"evt_{uuid.uuid4().hex[:12]}",
        "event_type": "worker.updated",
        "occurred_at": now,
        "ingested_at": now,
        "tenant_id": "ten_test",
        "site_id": "site_mel_01",
        "source": {"system": "deputy", "connection_id": "con_1", "record_id": "emp_123", "modified_at": now},
        "data": {},
        "quality": {"status": "accepted", "warnings": []},
    }
    envelope.update(overrides)
    return envelope


def test_ingestion_upserts_a_new_worker(client):
    response = client.post(
        "/v1/ingestion/events",
        json={
            "envelope": _worker_envelope(),
            "entity_type": "worker",
            "fields": {"employment_type": "permanent", "home_site": "site_mel_01"},
        },
        headers=_integration_header(),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "accepted"
    assert body["entity_id"] is not None

    with client.session_local() as session:
        worker = session.get(Worker, body["entity_id"])
    assert worker.source_system == "deputy"
    assert worker.source_ref == "emp_123"
    assert worker.employment_type == "permanent"


def test_resubmitting_the_same_record_upserts_not_duplicates(client):
    envelope = _worker_envelope()
    body = {"envelope": envelope, "entity_type": "worker", "fields": {"employment_type": "casual", "home_site": "site_mel_01"}}

    first = client.post("/v1/ingestion/events", json=body, headers=_integration_header())
    body["fields"]["employment_type"] = "permanent"
    second = client.post("/v1/ingestion/events", json=body, headers=_integration_header())

    assert first.json()["entity_id"] == second.json()["entity_id"]
    with client.session_local() as session:
        workers = session.query(Worker).filter_by(source_system="deputy", source_ref="emp_123").all()
    assert len(workers) == 1
    assert workers[0].employment_type == "permanent"


def test_quarantined_envelope_is_dead_lettered_not_upserted(client):
    envelope = _worker_envelope(quality={"status": "quarantined", "warnings": ["missing required field"]})
    response = client.post(
        "/v1/ingestion/events",
        json={"envelope": envelope, "entity_type": "worker", "fields": {}},
        headers=_integration_header(),
    )
    assert response.status_code == 202
    assert response.json()["status"] == "quarantined"
    with client.session_local() as session:
        workers = session.query(Worker).filter_by(source_system="deputy", source_ref="emp_123").all()
    assert workers == []


def test_tenant_binding_is_enforced(client):
    envelope = _worker_envelope(tenant_id="ten_someone_else")
    response = client.post(
        "/v1/ingestion/events",
        json={"envelope": envelope, "entity_type": "worker", "fields": {}},
        headers=_integration_header(),
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_unsupported_schema_version_is_rejected(client):
    envelope = _worker_envelope(schema_version="2.0")
    response = client.post(
        "/v1/ingestion/events",
        json={"envelope": envelope, "entity_type": "worker", "fields": {}},
        headers=_integration_header(),
    )
    assert response.status_code == 400
    assert "schema_version" in response.json()["detail"]


def test_unsupported_entity_type_is_rejected(client):
    response = client.post(
        "/v1/ingestion/events",
        json={"envelope": _worker_envelope(), "entity_type": "not_a_real_entity", "fields": {}},
        headers=_integration_header(),
    )
    assert response.status_code == 400
    assert "entity_type" in response.json()["detail"]


def test_ingestion_requires_labour_writeback_permission(client):
    response = client.post(
        "/v1/ingestion/events",
        json={"envelope": _worker_envelope(), "entity_type": "worker", "fields": {}},
        headers=context_header(roles=["operations_manager"]),
    )
    assert response.status_code == 403
