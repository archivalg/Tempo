"""3PL Cost-to-Serve & Margin — checks the property that makes this model
worth having: it evaluates customer demand on profitability, serving a
high-margin customer fully while leaving a customer whose contracted rate
doesn't cover the marginal cost of extra capacity partially unserved,
rather than treating all demand as equally worth serving (workforce_mix's
view).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.canonical import ActivityRoleZoneMap, DemandBucket, LabourCostRule, SellRateContract, WorkStandard
from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.base import InsufficientData
from app.solvers.margin_3pl import solve_margin_3pl

WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)
SITE_ID = "site_mel_01"


def _request() -> RunRequest:
    return RunRequest(
        request_id="req_test",
        scope=RunScope(tenant_id="ten_test", site_ids=[SITE_ID], customer_ids=["cust_A", "cust_B"]),
        planning_window=PlanningWindow(
            start=WINDOW_START, end=datetime(2026, 9, 15, tzinfo=timezone.utc), timezone="Australia/Melbourne", bucket_minutes=60
        ),
    )


def _seed_common(session) -> None:
    session.add(WorkStandard(tenant_id="ten_test", activity="picking", complexity_segment=None, time_per_unit_seconds=45.0, effective_from=WINDOW_START - timedelta(days=365)))
    session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id=SITE_ID, activity="picking", role="picker", zone="zone_a", weight=1.0))
    session.add(LabourCostRule(tenant_id="ten_test", labour_type="permanent", role="picker", rate="35.00", overtime_multiplier="1.5", surcharge=None, currency="AUD"))


def test_low_margin_customer_left_partially_unserved_when_uneconomic(client):
    with client.session_local() as db:
        _seed_common(db)
        db.add(DemandBucket(tenant_id="ten_test", activity="picking", site_id=SITE_ID, customer_id="cust_A", interval_start=WINDOW_START, volume=100.0, source="wms"))
        db.add(DemandBucket(tenant_id="ten_test", activity="picking", site_id=SITE_ID, customer_id="cust_B", interval_start=WINDOW_START, volume=5000.0, source="wms"))
        db.add(SellRateContract(tenant_id="ten_test", customer_id="cust_A", activity="picking", rate="5.00", currency="AUD", sla_penalty="2.00", effective_from=WINDOW_START - timedelta(days=30), effective_to=None))
        db.add(SellRateContract(tenant_id="ten_test", customer_id="cust_B", activity="picking", rate="0.01", currency="AUD", sla_penalty="0.001", effective_from=WINDOW_START - timedelta(days=30), effective_to=None))
        db.commit()
        outcome = solve_margin_3pl(db, "ten_test", [SITE_ID], _request())

    by_customer = {row["customer_id"]: row for row in outcome.result["by_customer"]}
    assert by_customer["cust_A"]["unserved_units"] == 0.0, "the profitable customer should be fully served"
    assert by_customer["cust_B"]["unserved_units"] > 0, "the uneconomic customer should be left partially unserved"
    assert outcome.feasibility == "feasible_with_slack"


def test_missing_contract_falls_back_to_default_rate_and_is_flagged(client):
    with client.session_local() as db:
        _seed_common(db)
        db.add(DemandBucket(tenant_id="ten_test", activity="picking", site_id=SITE_ID, customer_id="cust_A", interval_start=WINDOW_START, volume=100.0, source="wms"))
        db.commit()
        outcome = solve_margin_3pl(db, "ten_test", [SITE_ID], _request())

    assert outcome.result["by_customer"][0]["unserved_units"] == 0.0
    assert any("SellRateContract" in item for item in outcome.missing_evidence)


def test_no_customer_demand_raises_insufficient_data(client):
    with client.session_local() as db:
        _seed_common(db)
        db.commit()
        try:
            solve_margin_3pl(db, "ten_test", [SITE_ID], _request())
            raised = False
        except InsufficientData:
            raised = True

    assert raised
