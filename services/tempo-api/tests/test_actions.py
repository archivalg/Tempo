"""Controlled action pipeline — §12's two-step contract. Checks the
property that makes this model honest rather than decorative: with no real
vendor writeback connector, every execute() ends at 'unknown' (never a
fabricated 'confirmed'), and 'confirmed' only happens when a real
connector (simulated here by FakeWritebackClient, the same substitution
pattern connector tests use for fake HTTP clients) actually reports it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.api.v1.actions as actions_module
from app.maestro.writeback import WritebackOutcome
from app.models.runs import ActionRequest, Recommendation

from .conftest import context_header
from .test_run_endpoint import VALID_REQUEST, _headers, _seed

TARGET = {"system": "deputy", "connection_id": "con_1", "site_id": "site_mel_01"}


class FakeWritebackClient:
    def __init__(self, status: str = "confirmed", detail: str = "fake vendor accepted"):
        self.status = status
        self.detail = detail
        self.submit_calls = 0
        self.check_status_calls = 0

    def submit(self, action_type, target, payload):
        self.submit_calls += 1
        return WritebackOutcome(status=self.status, detail=self.detail)

    def check_status(self, action_type, target, payload):
        self.check_status_calls += 1
        return WritebackOutcome(status=self.status, detail=self.detail)


def _create_recommendation(client) -> str:
    """Assumes the shared canonical fixture (`_seed`) has already been
    seeded once for this client — calling it twice would re-insert the same
    fixed worker_ids and violate the primary key, so tests that need more
    than one recommendation call this again without reseeding.
    """
    response = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    return response.json()["recommendation_id"]


def _validate(client, recommendation_id: str, **overrides) -> dict:
    body = {
        "action_type": "publish_roster",
        "recommendation_id": recommendation_id,
        "target": TARGET,
        "expected_source_version": None,
        **overrides,
    }
    return client.post("/v1/actions/validate", json=body, headers=context_header())


def _execute(client, validated: dict, roles: list[str] | None = None) -> dict:
    body = {
        "action_type": "publish_roster",
        "recommendation_id": validated["recommendation_id"],
        "target": TARGET,
        "expected_source_version": None,
        "action_id": validated["action_id"],
        "action_token": validated["action_token"],
    }
    headers = context_header(roles=roles) if roles else context_header()
    headers["Idempotency-Key"] = str(uuid.uuid4())
    return client.post("/v1/actions", json=body, headers=headers)


def test_validate_then_execute_ends_unknown_with_no_real_writeback_client(client):
    _seed(client)
    recommendation_id = _create_recommendation(client)
    validate_resp = _validate(client, recommendation_id)
    assert validate_resp.status_code == 200, validate_resp.text
    validated = validate_resp.json()
    validated["recommendation_id"] = recommendation_id

    execute_resp = _execute(client, validated)
    assert execute_resp.status_code == 202
    body = execute_resp.json()
    assert body["status"] == "unknown", "no real writeback connector exists — must never fabricate 'confirmed'"


def test_execute_confirms_and_bumps_source_version_with_fake_client(client, monkeypatch):
    _seed(client)
    fake = FakeWritebackClient(status="confirmed")
    monkeypatch.setattr(actions_module, "writeback_client", fake)

    recommendation_id = _create_recommendation(client)
    validated = _validate(client, recommendation_id).json()
    validated["recommendation_id"] = recommendation_id
    execute_resp = _execute(client, validated)
    assert execute_resp.json()["status"] == "confirmed"
    assert fake.submit_calls == 1

    # The source version watermark bumped on confirm, so a second action
    # against the same target with the same (now stale) expected_source_version
    # must drift, not silently succeed.
    recommendation_id_2 = _create_recommendation(client)
    drift_resp = _validate(client, recommendation_id_2)
    assert drift_resp.status_code == 409
    assert drift_resp.json()["error_code"] == "TEMPO-ACTION-002"


def test_reconcile_resolves_an_unknown_outcome(client, monkeypatch):
    _seed(client)
    recommendation_id = _create_recommendation(client)
    validated = _validate(client, recommendation_id).json()
    validated["recommendation_id"] = recommendation_id
    execute_resp = _execute(client, validated)
    action_id = execute_resp.json()["action_id"]
    assert execute_resp.json()["status"] == "unknown"

    fake = FakeWritebackClient(status="confirmed", detail="resolved on reconciliation")
    monkeypatch.setattr(actions_module, "writeback_client", fake)

    reconcile_resp = client.post(f"/v1/actions/{action_id}/reconcile", headers=context_header())
    assert reconcile_resp.status_code == 202
    body = reconcile_resp.json()
    assert body["status"] == "confirmed"
    assert fake.check_status_calls == 1


def test_reconcile_on_terminal_action_is_a_noop(client, monkeypatch):
    _seed(client)
    fake = FakeWritebackClient(status="confirmed")
    monkeypatch.setattr(actions_module, "writeback_client", fake)

    recommendation_id = _create_recommendation(client)
    validated = _validate(client, recommendation_id).json()
    validated["recommendation_id"] = recommendation_id
    action_id = _execute(client, validated).json()["action_id"]

    reconcile_resp = client.post(f"/v1/actions/{action_id}/reconcile", headers=context_header())
    assert reconcile_resp.status_code == 202
    assert reconcile_resp.json()["status"] == "confirmed"
    assert fake.check_status_calls == 0, "reconciling an already-confirmed action must not re-query the source"


def test_action_type_mismatch_rejected(client):
    _seed(client)
    recommendation_id = _create_recommendation(client)
    response = _validate(client, recommendation_id, action_type="approve_leave")
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-ACTION-006"


def test_expired_recommendation_rejected(client):
    _seed(client)
    recommendation_id = _create_recommendation(client)
    with client.session_local() as db:
        recommendation = db.get(Recommendation, recommendation_id)
        recommendation.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    response = _validate(client, recommendation_id)
    assert response.status_code == 409
    assert response.json()["error_code"] == "TEMPO-ACTION-001"


def test_recommendation_not_found(client):
    response = _validate(client, "rec_does_not_exist")
    assert response.status_code == 404
    assert response.json()["error_code"] == "TEMPO-ACTION-005"


def test_execute_requires_labour_approve_permission(client):
    _seed(client)
    recommendation_id = _create_recommendation(client)
    validated = _validate(client, recommendation_id).json()
    validated["recommendation_id"] = recommendation_id

    response = _execute(client, validated, roles=["planner"])
    assert response.status_code == 403
    assert response.json()["error_code"] == "TEMPO-AUTH-002"


def test_execute_is_idempotent_with_same_key(client, monkeypatch):
    _seed(client)
    fake = FakeWritebackClient(status="confirmed")
    monkeypatch.setattr(actions_module, "writeback_client", fake)

    recommendation_id = _create_recommendation(client)
    validated = _validate(client, recommendation_id).json()
    validated["recommendation_id"] = recommendation_id

    body = {
        "action_type": "publish_roster",
        "recommendation_id": recommendation_id,
        "target": TARGET,
        "expected_source_version": None,
        "action_id": validated["action_id"],
        "action_token": validated["action_token"],
    }
    headers = context_header()
    headers["Idempotency-Key"] = "same-key-reused"
    first = client.post("/v1/actions", json=body, headers=headers)
    second = client.post("/v1/actions", json=body, headers=headers)

    assert first.json() == second.json()
    assert fake.submit_calls == 1, "a replayed Idempotency-Key must not re-run the writeback"


def test_tampered_action_token_rejected(client):
    _seed(client)
    recommendation_id = _create_recommendation(client)
    validated = _validate(client, recommendation_id).json()
    validated["recommendation_id"] = recommendation_id
    validated["action_token"] = validated["action_token"][:-4] + "0000"

    response = _execute(client, validated)
    # Caught by the stored action_token_hash comparison before the token's
    # own HMAC signature is even checked — either way, a tampered token
    # must never execute.
    assert response.status_code == 409
    assert response.json()["error_code"] == "TEMPO-ACTION-002"


def test_expired_action_token_rejected(client):
    _seed(client)
    recommendation_id = _create_recommendation(client)
    validated = _validate(client, recommendation_id).json()
    validated["recommendation_id"] = recommendation_id

    with client.session_local() as db:
        action = db.get(ActionRequest, validated["action_id"])
        action.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    response = _execute(client, validated)
    assert response.status_code == 409
    assert response.json()["error_code"] == "TEMPO-ACTION-001"


def test_get_action_returns_current_state(client):
    _seed(client)
    recommendation_id = _create_recommendation(client)
    validated = _validate(client, recommendation_id).json()

    response = client.get(f"/v1/actions/{validated['action_id']}", headers=context_header())
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "validated"
    assert body["action_type"] == "publish_roster"


def test_list_actions_returns_newest_first_and_filters_by_status(client):
    _seed(client)
    first_id = _validate(client, _create_recommendation(client)).json()["action_id"]
    second_id = _validate(client, _create_recommendation(client)).json()["action_id"]

    listed = client.get("/v1/actions", headers=context_header()).json()
    assert [a["action_id"] for a in listed["actions"]] == [second_id, first_id]

    filtered = client.get("/v1/actions?status=validated", headers=context_header()).json()
    assert all(a["status"] == "validated" for a in filtered["actions"])
