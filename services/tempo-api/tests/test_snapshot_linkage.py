"""DAT-06: "Persist immutable optimisation input snapshots and link every
run, recommendation and action to its snapshot." Proves the manifest is a
real, populated row -- not just a bare generated ID string -- and that
recommendation/action both carry the same snapshot_id as their originating
run, without requiring a join to find it.
"""
from __future__ import annotations

from app.models.runs import ActionRequest, OptimisationSnapshot, Recommendation

from .conftest import context_header
from .test_run_endpoint import VALID_REQUEST, _headers, _seed


def test_run_creation_persists_a_snapshot_manifest(client):
    _seed(client)
    body = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers()).json()
    run_id = body["run_id"]

    with client.session_local() as session:
        snapshot = session.query(OptimisationSnapshot).filter_by(run_id=run_id).one()

    assert snapshot.tenant_id == "ten_test"
    # content_hash is app.core.idempotency.hash_payload over the server's
    # full RunRequest.model_dump (defaults filled in), not the raw request
    # body -- exact reproducibility of *that* is covered by the "identical
    # requests hash identically" test below; here just check it looks like
    # a real sha256 hex digest, not an empty/placeholder string.
    assert len(snapshot.content_hash) == 64
    int(snapshot.content_hash, 16)  # raises if not valid hex
    assert snapshot.policy_version is not None


def test_recommendation_and_action_carry_the_runs_snapshot_id(client):
    _seed(client)
    body = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers()).json()
    run_id, recommendation_id = body["run_id"], body["recommendation_id"]

    with client.session_local() as session:
        snapshot = session.query(OptimisationSnapshot).filter_by(run_id=run_id).one()
        recommendation = session.get(Recommendation, recommendation_id)

    assert recommendation.snapshot_id == snapshot.snapshot_id

    action_id = client.post(
        "/v1/actions/validate",
        json={
            "action_type": "publish_roster",
            "recommendation_id": recommendation_id,
            "target": {"system": "deputy", "connection_id": "con_1", "site_id": "site_mel_01"},
        },
        headers=context_header(),
    ).json()["action_id"]

    with client.session_local() as session:
        action = session.get(ActionRequest, action_id)

    assert action.snapshot_id == snapshot.snapshot_id


def test_identical_requests_produce_identical_content_hashes(client):
    # A weaker but real property, given content_hash covers the RunRequest
    # only (see OptimisationSnapshot's own docstring for the disclosed
    # limitation): the same request, submitted twice with different
    # idempotency keys, hashes identically both times.
    _seed(client)
    first = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers()).json()
    second = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers()).json()
    assert first["run_id"] != second["run_id"]

    with client.session_local() as session:
        hash_one = session.query(OptimisationSnapshot).filter_by(run_id=first["run_id"]).one().content_hash
        hash_two = session.query(OptimisationSnapshot).filter_by(run_id=second["run_id"]).one().content_hash

    assert hash_one == hash_two
