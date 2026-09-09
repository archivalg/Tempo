"""Leave & RDO Planning — checks the actual property that makes this model
worth having: when granting every request would create a staffing gap, it
rejects the lowest-priority ones first rather than approving blindly.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.canonical import Availability
from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.leave_rdo import solve_leave_rdo
from .factories import seed_named_roster_scenario

WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)
SITE_ID = "site_mel_01"


def _request() -> RunRequest:
    return RunRequest(
        request_id="req_test",
        scope=RunScope(tenant_id="ten_test", site_ids=[SITE_ID], customer_ids=["cust_A"]),
        planning_window=PlanningWindow(
            start=WINDOW_START, end=datetime(2026, 9, 15, tzinfo=timezone.utc),
            timezone="Australia/Melbourne", bucket_minutes=60,
        ),
    )


def test_scarcity_rejects_lowest_priority_requests_first(client):
    with client.session_local() as db:
        seed_named_roster_scenario(db, tenant_id="ten_test", site_id=SITE_ID, window_start=WINDOW_START)
        # All 5 workers request leave on the same day; only ~2/day are
        # actually needed, so approving everyone would create a real gap.
        preferences = {"wrk_0": 1.0, "wrk_1": 5.0, "wrk_2": 2.0, "wrk_3": 9.0, "wrk_4": 3.0}
        for worker_id, pref in preferences.items():
            db.add(
                Availability(
                    tenant_id="ten_test", worker_id=worker_id,
                    interval_start=WINDOW_START, interval_end=WINDOW_START + timedelta(hours=8),
                    status="leave_requested", preference=pref,
                )
            )
        db.commit()

        outcome = solve_leave_rdo(db, "ten_test", [SITE_ID], _request())

    by_worker = {d["worker_id"]: d for d in outcome.result["decisions"]}
    assert not by_worker["wrk_0"]["approved"], "lowest-priority request should be rejected under scarcity"
    assert not by_worker["wrk_2"]["approved"], "second-lowest-priority request should be rejected under scarcity"
    assert by_worker["wrk_3"]["approved"], "highest-priority request should be approved"

    assert outcome.baseline["shortfall_count"] > outcome.proposed["shortfall_count"], (
        "approving everyone (baseline) should create more shortfall than the balanced plan"
    )
    assert outcome.result["kpis"]["remaining_shortfall"] == 0.0


def test_no_pending_requests_raises_insufficient_data(client):
    from app.solvers.base import InsufficientData

    with client.session_local() as db:
        seed_named_roster_scenario(db, tenant_id="ten_test", site_id=SITE_ID, window_start=WINDOW_START)
        try:
            solve_leave_rdo(db, "ten_test", [SITE_ID], _request())
            assert False, "expected InsufficientData with no pending requests"
        except InsufficientData:
            pass


def test_ample_supply_approves_every_request(client):
    with client.session_local() as db:
        seed_named_roster_scenario(db, tenant_id="ten_test", site_id=SITE_ID, window_start=WINDOW_START)
        db.add(
            Availability(
                tenant_id="ten_test", worker_id="wrk_0",
                interval_start=WINDOW_START, interval_end=WINDOW_START + timedelta(hours=8),
                status="leave_requested", preference=1.0,
            )
        )
        db.commit()
        outcome = solve_leave_rdo(db, "ten_test", [SITE_ID], _request())

    assert outcome.result["decisions"][0]["approved"] is True
    assert outcome.result["kpis"]["rejected_count"] == 0
