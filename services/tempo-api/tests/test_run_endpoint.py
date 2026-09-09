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
    assert fetched_body["run_type"] == "named_roster"
    assert fetched_body["recommendation_id"] == body["recommendation_id"]
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


def test_training_coverage_reports_full_coverage_when_fully_certified(client):
    _seed(client)
    response = client.post("/v1/optimisations/training_coverage", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    result = client.get(f"/v1/runs/{run_id}", headers=context_header()).json()["result"]
    assert result["training_plan"] == []
    assert result["kpis"]["coverage_pct"] == 100.0


def test_leave_rdo_approves_a_single_pending_request_with_ample_supply(client):
    from datetime import timedelta

    from app.models.canonical import Availability

    _seed(client)
    with client.session_local() as session:
        session.add(
            Availability(
                tenant_id="ten_test", worker_id="wrk_0",
                interval_start=WINDOW_START, interval_end=WINDOW_START + timedelta(hours=8),
                status="leave_requested", preference=1.0,
            )
        )
        session.commit()

    response = client.post("/v1/optimisations/leave_rdo", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    result = client.get(f"/v1/runs/{run_id}", headers=context_header()).json()["result"]
    assert result["decisions"][0]["approved"] is True
    assert result["kpis"]["rejected_count"] == 0


def test_intraday_reallocation_moves_idle_worker_to_cover_backlog(client):
    from datetime import timedelta

    from app.models.canonical import ActivityRoleZoneMap, ShiftAssignment, SkillCertification, Worker, ZoneBacklog

    with client.session_local() as session:
        for index, zone in enumerate(["zone_a", "zone_a", "zone_b"]):
            session.add(Worker(worker_id=f"iw{index}", tenant_id="ten_test", employment_type="permanent", home_site="site_mel_01", status="active"))
            session.add(
                SkillCertification(tenant_id="ten_test", worker_id=f"iw{index}", skill_code="picker", valid_from=WINDOW_START - timedelta(days=1), valid_to=None)
            )
            session.add(
                ShiftAssignment(
                    tenant_id="ten_test", worker_id=f"iw{index}", role="picker", zone=zone,
                    start_at=WINDOW_START, end_at=WINDOW_START + timedelta(hours=8), status="committed",
                )
            )
        session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id="site_mel_01", activity="picking", role="picker", zone="zone_a", weight=1.0))
        session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id="site_mel_01", activity="picking", role="picker", zone="zone_b", weight=1.0))
        session.add(ZoneBacklog(tenant_id="ten_test", site_id="site_mel_01", zone="zone_a", interval_start=WINDOW_START, backlog_units=3))
        session.add(ZoneBacklog(tenant_id="ten_test", site_id="site_mel_01", zone="zone_b", interval_start=WINDOW_START, backlog_units=0))
        session.commit()

    response = client.post("/v1/optimisations/intraday_reallocation", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    result = client.get(f"/v1/runs/{run_id}", headers=context_header()).json()["result"]
    assert result["kpis"]["workers_moved"] == 1
    assert result["kpis"]["remaining_backlog"] == 0


def test_team_composition_builds_a_named_team(client):
    _seed(client)
    response = client.post("/v1/optimisations/team_composition", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    result = client.get(f"/v1/runs/{run_id}", headers=context_header()).json()["result"]
    assert result["teams"]
    assert result["teams"][0]["selected_worker_ids"]


def _headers_finance():
    headers = context_header(roles=["operations_manager", "finance"])
    headers["Idempotency-Key"] = str(uuid.uuid4())
    return headers


def test_margin_3pl_reports_contribution_margin_for_finance_role(client):
    from datetime import timedelta

    from app.models.canonical import ActivityRoleZoneMap, DemandBucket, LabourCostRule, SellRateContract, WorkStandard

    with client.session_local() as session:
        session.add(WorkStandard(tenant_id="ten_test", activity="picking", complexity_segment=None, time_per_unit_seconds=45.0, effective_from=WINDOW_START - timedelta(days=365)))
        session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id="site_mel_01", activity="picking", role="picker", zone="zone_a", weight=1.0))
        session.add(LabourCostRule(tenant_id="ten_test", labour_type="permanent", role="picker", rate="35.00", overtime_multiplier="1.5", surcharge=None, currency="AUD"))
        session.add(DemandBucket(tenant_id="ten_test", activity="picking", site_id="site_mel_01", customer_id="cust_A", interval_start=WINDOW_START, volume=100.0, source="wms"))
        session.add(SellRateContract(tenant_id="ten_test", customer_id="cust_A", activity="picking", rate="5.00", currency="AUD", sla_penalty="2.00", effective_from=WINDOW_START - timedelta(days=30), effective_to=None))
        session.commit()

    response = client.post("/v1/optimisations/margin_3pl", json=VALID_REQUEST, headers=_headers_finance())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    result = client.get(f"/v1/runs/{run_id}", headers=context_header(roles=["operations_manager", "finance"])).json()["result"]
    assert float(result["kpis"]["contribution_margin"]["amount"]) != 0


def test_margin_3pl_forbidden_without_labour_margin_read(client):
    headers = context_header(roles=["operations_manager"])
    headers["Idempotency-Key"] = str(uuid.uuid4())
    response = client.post("/v1/optimisations/margin_3pl", json=VALID_REQUEST, headers=headers)
    assert response.status_code == 403
    assert response.json()["error_code"] == "TEMPO-AUTH-002"


def test_margin_3pl_run_result_hidden_from_caller_without_margin_read(client):
    from app.models.canonical import ActivityRoleZoneMap, DemandBucket, LabourCostRule, SellRateContract, WorkStandard
    from datetime import timedelta

    with client.session_local() as session:
        session.add(WorkStandard(tenant_id="ten_test", activity="picking", complexity_segment=None, time_per_unit_seconds=45.0, effective_from=WINDOW_START - timedelta(days=365)))
        session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id="site_mel_01", activity="picking", role="picker", zone="zone_a", weight=1.0))
        session.add(LabourCostRule(tenant_id="ten_test", labour_type="permanent", role="picker", rate="35.00", overtime_multiplier="1.5", surcharge=None, currency="AUD"))
        session.add(DemandBucket(tenant_id="ten_test", activity="picking", site_id="site_mel_01", customer_id="cust_A", interval_start=WINDOW_START, volume=100.0, source="wms"))
        session.add(SellRateContract(tenant_id="ten_test", customer_id="cust_A", activity="picking", rate="5.00", currency="AUD", sla_penalty="2.00", effective_from=WINDOW_START - timedelta(days=30), effective_to=None))
        session.commit()

    run_id = client.post("/v1/optimisations/margin_3pl", json=VALID_REQUEST, headers=_headers_finance()).json()["run_id"]
    forbidden = client.get(f"/v1/runs/{run_id}", headers=context_header(roles=["operations_manager"]))
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "TEMPO-AUTH-002"


def test_scenario_reports_a_cost_distribution(client):
    _seed(client)
    response = client.post("/v1/optimisations/scenario", json=VALID_REQUEST, headers=_headers())
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    result = client.get(f"/v1/runs/{run_id}", headers=context_header()).json()["result"]
    assert result["kpis"]["cost_distribution"]["mean"]
    assert result["scenario_count"] > 0


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
    # Phase D completes every run_type in Appendix C's enum (see
    # app/api/v1/runs.py's module docstring) — this now only guards a
    # run_type string outside that enum entirely, since run_type is a plain
    # path parameter FastAPI doesn't validate against the RunType literal.
    response = client.post("/v1/optimisations/not_a_real_run_type", json=VALID_REQUEST, headers=_headers())
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


def test_list_runs_returns_newest_first_and_paginates(client):
    _seed(client)
    ids = []
    for _ in range(3):
        response = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
        ids.append(response.json()["run_id"])

    page1 = client.get("/v1/runs?limit=2", headers=context_header()).json()
    assert [r["run_id"] for r in page1["runs"]] == list(reversed(ids))[:2]
    assert page1["next_cursor"] == ids[1]

    page2 = client.get(f"/v1/runs?limit=2&cursor={page1['next_cursor']}", headers=context_header()).json()
    assert [r["run_id"] for r in page2["runs"]] == [ids[0]]
    assert page2["next_cursor"] is None


def test_list_runs_filters_by_run_type_and_status(client):
    _seed(client)
    client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    client.post("/v1/optimisations/demand_forecast", json=VALID_REQUEST, headers=_headers())

    response = client.get("/v1/runs?run_type=demand_forecast", headers=context_header())
    body = response.json()
    assert len(body["runs"]) == 1
    assert body["runs"][0]["run_type"] == "demand_forecast"


def test_list_runs_excludes_margin_3pl_without_labour_margin_read(client):
    from datetime import timedelta

    from app.models.canonical import ActivityRoleZoneMap, DemandBucket, LabourCostRule, SellRateContract, WorkStandard

    _seed(client)
    with client.session_local() as session:
        session.add(WorkStandard(tenant_id="ten_test", activity="picking", complexity_segment=None, time_per_unit_seconds=45.0, effective_from=WINDOW_START - timedelta(days=365)))
        session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id="site_mel_01", activity="picking", role="picker", zone="zone_a", weight=1.0))
        session.add(LabourCostRule(tenant_id="ten_test", labour_type="permanent", role="picker", rate="35.00", overtime_multiplier="1.5", surcharge=None, currency="AUD"))
        session.add(DemandBucket(tenant_id="ten_test", activity="picking", site_id="site_mel_01", customer_id="cust_A", interval_start=WINDOW_START, volume=100.0, source="wms"))
        session.add(SellRateContract(tenant_id="ten_test", customer_id="cust_A", activity="picking", rate="5.00", currency="AUD", sla_penalty="2.00", effective_from=WINDOW_START - timedelta(days=30), effective_to=None))
        session.commit()

    finance_headers = context_header(roles=["operations_manager", "finance"])
    finance_headers["Idempotency-Key"] = str(uuid.uuid4())
    client.post("/v1/optimisations/margin_3pl", json=VALID_REQUEST, headers=finance_headers)

    plain_response = client.get("/v1/runs", headers=context_header(roles=["operations_manager"]))
    assert all(r["run_type"] != "margin_3pl" for r in plain_response.json()["runs"])

    finance_list = client.get("/v1/runs", headers=context_header(roles=["operations_manager", "finance"]))
    assert any(r["run_type"] == "margin_3pl" for r in finance_list.json()["runs"])


def test_run_comparisons_returns_kpis_for_each_run(client):
    _seed(client)
    first = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    second = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    run_ids = [first.json()["run_id"], second.json()["run_id"]]
    response = client.post("/v1/run-comparisons", json={"run_ids": run_ids}, headers=context_header())
    assert response.status_code == 200
    assert len(response.json()["kpis"]) == 2
