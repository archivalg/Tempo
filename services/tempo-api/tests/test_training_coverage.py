"""Training & Certification Coverage — checks the actual property that
makes this model worth having: required coverage must come from the
underlying labour-hours need, not from workforce_mix's already
certification-gated headcount (which can never show a shortfall against
itself — see the solver module's docstring for why that was a real design
bug caught while building this).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.canonical import ActivityRoleZoneMap, DemandBucket, LabourCostRule, SkillCertification, Worker, WorkStandard
from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.training_coverage import solve_training_coverage

WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)
SITE_ID = "site_mel_01"


def _request() -> RunRequest:
    return RunRequest(
        request_id="req_test",
        scope=RunScope(tenant_id="ten_test", site_ids=[SITE_ID], customer_ids=["cust_A"]),
        planning_window=PlanningWindow(
            start=WINDOW_START, end=datetime(2026, 9, 15, tzinfo=timezone.utc), timezone="Australia/Melbourne", bucket_minutes=60
        ),
    )


def _seed_high_demand_scarce_certification(session) -> None:
    for hours_back in range(4 * 24, 0, -1):
        session.add(
            DemandBucket(
                tenant_id="ten_test", activity="picking", site_id=SITE_ID, customer_id=None,
                interval_start=WINDOW_START - timedelta(hours=hours_back), volume=500.0, source="tempo_native",
            )
        )
    session.add(WorkStandard(tenant_id="ten_test", activity="picking", complexity_segment=None, time_per_unit_seconds=45.0, effective_from=WINDOW_START - timedelta(days=365)))
    session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id=SITE_ID, activity="picking", role="picker", zone="zone_a", weight=1.0))
    for labour_type, rate in [("permanent", "35.00"), ("casual", "32.00"), ("labour_hire", "45.00")]:
        session.add(
            LabourCostRule(
                tenant_id="ten_test", labour_type=labour_type, role="picker", rate=rate,
                overtime_multiplier="1.5", surcharge="10.00" if labour_type == "labour_hire" else None, currency="AUD",
            )
        )
    for index, employment_type in enumerate(["permanent", "permanent", "casual", "casual", "labour_hire"]):
        session.add(Worker(worker_id=f"w{index}", tenant_id="ten_test", employment_type=employment_type, home_site=SITE_ID, status="active"))
    # Only w0 is currently certified — everyone else is a training candidate.
    session.add(SkillCertification(tenant_id="ten_test", worker_id="w0", skill_code="picker", valid_from=WINDOW_START - timedelta(days=1), valid_to=None))
    session.commit()


def test_training_plan_only_targets_uncertified_workers_and_reduces_shortfall(client):
    with client.session_local() as db:
        _seed_high_demand_scarce_certification(db)
        outcome = solve_training_coverage(db, "ten_test", [SITE_ID], _request())

    trained_workers = {row["worker_id"] for row in outcome.result["training_plan"]}
    assert "w0" not in trained_workers, "w0 is already certified — training them again is waste, not a real need"
    assert trained_workers, "expected at least one training recommendation given severe scarcity"

    baseline_shortfall = outcome.baseline["shortfall_count"]
    proposed_shortfall = outcome.proposed["shortfall_count"]
    assert proposed_shortfall < baseline_shortfall, "training should reduce shortfall relative to training nobody"


def test_fully_staffed_scenario_recommends_no_training(client):
    from .factories import seed_named_roster_scenario

    with client.session_local() as db:
        seed_named_roster_scenario(db, tenant_id="ten_test", site_id=SITE_ID, window_start=WINDOW_START)
        outcome = solve_training_coverage(db, "ten_test", [SITE_ID], _request())

    assert outcome.result["training_plan"] == []
    assert outcome.result["kpis"]["remaining_shortfall"] == 0.0
    assert outcome.feasibility == "feasible"
