"""Team Composition — checks the property that makes this model worth
having: it selects named workers to hit productivity/quality targets while
respecting the mentor-coverage floor, not just the cheapest/first-found
workers off the eligible list.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.canonical import WorkerPerformanceProfile
from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.team_composition import solve_team_composition
from .factories import seed_named_roster_scenario

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


def test_mentor_floor_is_respected_when_a_mentor_is_eligible(client):
    with client.session_local() as db:
        seed_named_roster_scenario(db, tenant_id="ten_test", site_id=SITE_ID, window_start=WINDOW_START)
        db.add(
            WorkerPerformanceProfile(
                worker_id="wrk_0", tenant_id="ten_test",
                productivity_index=1.0, quality_index=1.0, reliability_index=1.0, is_mentor=True,
            )
        )
        db.commit()
        outcome = solve_team_composition(db, "ten_test", [SITE_ID], _request())

    assert outcome.result["teams"], "expected at least one team built"
    team = outcome.result["teams"][0]
    assert "wrk_0" in team["selected_worker_ids"], "the only mentor must be selected to satisfy the mentor-min floor"


def test_workers_with_no_profile_are_assumed_average_not_excluded(client):
    with client.session_local() as db:
        seed_named_roster_scenario(db, tenant_id="ten_test", site_id=SITE_ID, window_start=WINDOW_START)
        outcome = solve_team_composition(db, "ten_test", [SITE_ID], _request())

    assert outcome.result["teams"]
    team = outcome.result["teams"][0]
    assert len(team["selected_worker_ids"]) == team["required_headcount"]
    assert outcome.feasibility == "feasible"


def test_no_certified_worker_at_all_raises_insufficient_data(client):
    """workforce_mix's own availability lookup is certification-gated too
    (same convention team_composition uses), so with zero certified workers
    it assigns zero headcount everywhere — team_composition correctly has
    nothing to build a team around and propagates InsufficientData rather
    than fabricating an empty team.
    """
    from app.solvers.base import InsufficientData
    from app.models.canonical import ActivityRoleZoneMap, DemandBucket, LabourCostRule, WorkStandard
    from datetime import timedelta

    with client.session_local() as db:
        for hours_back in range(4 * 24, 0, -1):
            db.add(
                DemandBucket(
                    tenant_id="ten_test", activity="picking", site_id=SITE_ID, customer_id=None,
                    interval_start=WINDOW_START - timedelta(hours=hours_back), volume=50.0, source="tempo_native",
                )
            )
        db.add(WorkStandard(tenant_id="ten_test", activity="picking", complexity_segment=None, time_per_unit_seconds=45.0, effective_from=WINDOW_START - timedelta(days=365)))
        db.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id=SITE_ID, activity="picking", role="picker", zone="zone_a", weight=1.0))
        db.add(LabourCostRule(tenant_id="ten_test", labour_type="permanent", role="picker", rate="35.00", overtime_multiplier="1.5", surcharge=None, currency="AUD"))
        db.commit()

        try:
            solve_team_composition(db, "ten_test", [SITE_ID], _request())
            raised = False
        except InsufficientData:
            raised = True

    assert raised, "no workers at all are certified for 'picker' — nothing to build a team from"
