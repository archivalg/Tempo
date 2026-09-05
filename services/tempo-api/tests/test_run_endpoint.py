import uuid
from datetime import datetime, timezone

from .conftest import context_header
from .factories import seed_named_roster_scenario

VALID_REQUEST = {
    "request_id": "req_1",
    "scope": {"tenant_id": "ten_test", "site_ids": ["site_mel_01"], "customer_ids": ["cust_A"]},
    "planning_window": {
        "start": "2026-09-08T00:00:00Z",
        "end": "2026-09-15T00:00:00Z",
        "timezone": "Australia/Melbourne",
        "bucket_minutes": 60,
    },
}
WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)


def _headers():
    headers = context_header()
    headers["Idempotency-Key"] = str(uuid.uuid4())
    return headers


def _seed(client):
    with client.session_local() as session:
        seed_named_roster_scenario(session, tenant_id="ten_test", site_id="site_mel_01", window_start=WINDOW_START)


def test_create_run_end_to_end(client):
    _seed(client)
    response = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] in {"completed", "completed_with_warnings"}
    assert body["run_id"].startswith("run_")

    run_id = body["run_id"]
    fetched = client.get(f"/v1/runs/{run_id}", headers=context_header())
    assert fetched.status_code == 200
    fetched_body = fetched.json()
    explanation = fetched_body["explanation"]
    for field in [
        "baseline",
        "proposed",
        "delta",
        "confidence",
        "primary_drivers",
        "data_lineage",
        "freshness",
        "missing_evidence",
        "feasibility",
        "evidence_ref",
    ]:
        assert field in explanation, f"missing mandatory explanation field: {field}"
    assert explanation["confidence"]["method"] == "tempo-confidence-1.0"
    assert fetched_body["result"]["assignments"], "expected the CP-SAT roster to actually assign someone"


def test_demand_forecast_produces_a_real_forecast(client):
    _seed(client)
    response = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    result = client.get(f"/v1/runs/{run_id}", headers=context_header()).json()["result"]
    assert result["forecast"]
    assert result["kpis"]["activities_forecast"] == 1


def test_workforce_mix_respects_internal_hire_ratio(client):
    _seed(client)
    response = client.post("/v1/optimisations/workforce_mix", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    result = client.get(f"/v1/runs/{run_id}", headers=context_header()).json()["result"]
    assert result["assignments"]
    assert float(result["kpis"]["labour_cost"]["amount"]) > 0


def test_demand_forecast_without_history_returns_data_not_ready(client):
    response = client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 422
    assert response.json()["error_code"] == "TEMPO-DATA-004"


def test_idempotent_replay_returns_same_run(client):
    _seed(client)
    headers = _headers()
    first = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=headers)
    second = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=headers)
    assert first.json()["run_id"] == second.json()["run_id"]


def test_idempotency_key_reuse_with_different_body_conflicts(client):
    _seed(client)
    headers = _headers()
    other_request = {**VALID_REQUEST, "request_id": "req_2"}
    client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=headers)
    response = client.post("/v1/optimisations/named_roster", json=other_request, headers=headers)
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_missing_idempotency_key_rejected(client):
    response = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=context_header())
    assert response.status_code == 400


def test_unimplemented_run_type_returns_not_implemented(client):
    response = client.post("/v1/optimisations/scenario", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 501
    assert response.json()["error_code"] == "TEMPO-RUN-004"


def test_scope_outside_caller_authorisation_rejected(client):
    request = {**VALID_REQUEST, "scope": {**VALID_REQUEST["scope"], "site_ids": ["site_other"]}}
    response = client.post("/v1/optimisations/named_roster", json=request, headers=_headers())
    assert response.status_code == 400
    assert response.json()["error_code"] == "TEMPO-SCOPE-001"


def test_caller_without_labour_plan_permission_forbidden(client):
    headers = context_header(roles=["supervisor"])
    headers["Idempotency-Key"] = str(uuid.uuid4())
    response = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=headers)
    assert response.status_code == 403
    assert response.json()["error_code"] == "TEMPO-AUTH-002"


def test_run_not_found_for_unknown_id(client):
    response = client.get("/v1/runs/does-not-exist", headers=context_header())
    assert response.status_code == 404
    assert response.json()["error_code"] == "TEMPO-RUN-001"


def test_cancel_terminal_run_is_a_noop(client):
    _seed(client)
    created = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    run_id = created.json()["run_id"]
    cancelled = client.post(f"/v1/runs/{run_id}/cancel", headers=context_header())
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == created.json()["status"]


def test_run_comparisons_returns_kpis_for_each_run(client):
    _seed(client)
    first = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    second = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    run_ids = [first.json()["run_id"], second.json()["run_id"]]
    response = client.post("/v1/run-comparisons", json={"run_ids": run_ids}, headers=context_header())
    assert response.status_code == 200
    assert len(response.json()["kpis"]) == 2
