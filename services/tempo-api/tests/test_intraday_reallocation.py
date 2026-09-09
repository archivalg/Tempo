"""Intraday Reallocation — checks the actual property that makes this
model worth having: it moves an idle worker to clear a live backlog gap,
at minimum disruption (leaves adequately-staffed zones alone).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.canonical import ActivityRoleZoneMap, ShiftAssignment, SkillCertification, Worker, ZoneBacklog
from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.base import InsufficientData
from app.solvers.intraday_reallocation import solve_intraday_reallocation

WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)
SITE_ID = "site_mel_01"


def _request(bucket_minutes: int = 60) -> RunRequest:
    return RunRequest(
        request_id="req_test",
        scope=RunScope(tenant_id="ten_test", site_ids=[SITE_ID], customer_ids=["cust_A"]),
        planning_window=PlanningWindow(
            start=WINDOW_START, end=WINDOW_START + timedelta(hours=1), timezone="Australia/Melbourne", bucket_minutes=bucket_minutes
        ),
    )


def _seed_two_zone_scenario(session, backlog_a: float, backlog_b: float) -> None:
    for index, zone in enumerate(["zone_a", "zone_a", "zone_b"]):
        session.add(Worker(worker_id=f"w{index}", tenant_id="ten_test", employment_type="permanent", home_site=SITE_ID, status="active"))
        session.add(
            SkillCertification(tenant_id="ten_test", worker_id=f"w{index}", skill_code="picker", valid_from=WINDOW_START - timedelta(days=1), valid_to=None)
        )
        session.add(
            ShiftAssignment(
                tenant_id="ten_test", worker_id=f"w{index}", role="picker", zone=zone,
                start_at=WINDOW_START, end_at=WINDOW_START + timedelta(hours=8), status="committed",
            )
        )
    session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id=SITE_ID, activity="picking", role="picker", zone="zone_a", weight=1.0))
    session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id=SITE_ID, activity="picking", role="picker", zone="zone_b", weight=1.0))
    session.add(ZoneBacklog(tenant_id="ten_test", site_id=SITE_ID, zone="zone_a", interval_start=WINDOW_START, backlog_units=backlog_a))
    session.add(ZoneBacklog(tenant_id="ten_test", site_id=SITE_ID, zone="zone_b", interval_start=WINDOW_START, backlog_units=backlog_b))
    session.commit()


def test_idle_worker_moves_to_clear_backlog_gap(client):
    with client.session_local() as db:
        # zone_a: 2 workers, 3 units of backlog (1 short); zone_b: 1 idle worker, no backlog.
        _seed_two_zone_scenario(db, backlog_a=3, backlog_b=0)
        outcome = solve_intraday_reallocation(db, "ten_test", [SITE_ID], _request())

    by_worker = {r["worker_id"]: r for r in outcome.result["reassignments"]}
    assert by_worker["w2"]["moved"] is True
    assert by_worker["w2"]["to_zone"] == "zone_a"
    assert by_worker["w0"]["moved"] is False
    assert by_worker["w1"]["moved"] is False
    assert outcome.result["kpis"]["remaining_backlog"] == 0
    assert outcome.baseline["remaining_backlog"] == 1.0, "baseline (no reallocation) should show the gap this move fixes"


def test_adequately_staffed_zones_see_no_movement(client):
    with client.session_local() as db:
        # Both zones already have exactly the backlog their current workers can cover.
        _seed_two_zone_scenario(db, backlog_a=2, backlog_b=1)
        outcome = solve_intraday_reallocation(db, "ten_test", [SITE_ID], _request())

    assert outcome.result["kpis"]["workers_moved"] == 0
    assert outcome.result["kpis"]["remaining_backlog"] == 0
    assert outcome.feasibility == "feasible"


def test_no_backlog_data_raises_insufficient_data(client):
    with client.session_local() as db:
        for index, zone in enumerate(["zone_a"]):
            db.add(Worker(worker_id=f"w{index}", tenant_id="ten_test", employment_type="permanent", home_site=SITE_ID, status="active"))
            db.add(
                ShiftAssignment(
                    tenant_id="ten_test", worker_id=f"w{index}", role="picker", zone=zone,
                    start_at=WINDOW_START, end_at=WINDOW_START + timedelta(hours=8), status="committed",
                )
            )
        db.commit()
        try:
            solve_intraday_reallocation(db, "ten_test", [SITE_ID], _request())
            assert False, "expected InsufficientData with no ZoneBacklog rows"
        except InsufficientData:
            pass
