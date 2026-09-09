"""Capacity/performance tests — §15.1's SLO table ("Simple run completion:
p95 <= 30 seconds... Mix/roster/training/leave at agreed pilot scale",
"Intraday recommendation: p95 <= 60 seconds") and §16.1's Solver test layer
requirement for "performance" evidence, not just correctness. Real solvers,
a synthetic dataset sized well above the smaller fixtures every other
solver test uses (150 workers x 21 days), and a wall-clock assertion —
this is a regression guard against a future change silently making a
solver scale badly, not just a smoke test that it runs at all.

150 workers x 21 days was chosen empirically: it's comfortably above what
a single warehouse site plans in one run, and named_roster (the slowest
model here, CP-SAT with the largest variable count) still finishes in
single-digit seconds on this hardware — an order of magnitude under the
spec's 30s target, leaving real headroom before this test would start
flagging a genuine regression.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from app.models.canonical import (
    ActivityRoleZoneMap,
    Availability,
    DemandBucket,
    LabourCostRule,
    SellRateContract,
    ShiftAssignment,
    SkillCertification,
    Worker,
    WorkStandard,
    ZoneBacklog,
)
from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.intraday_reallocation import solve_intraday_reallocation
from app.solvers.leave_rdo import solve_leave_rdo
from app.solvers.margin_3pl import solve_margin_3pl
from app.solvers.named_roster import solve_named_roster
from app.solvers.scenario import solve_scenario
from app.solvers.team_composition import solve_team_composition
from app.solvers.training_coverage import solve_training_coverage
from app.solvers.workforce_mix import solve_workforce_mix

WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)
SITE_ID = "site_mel_01"
NUM_WORKERS = 150
NUM_DAYS = 21
EMPLOYMENT_TYPES = ["permanent", "permanent", "permanent", "casual", "casual", "labour_hire"]
ZONES = ["zone_a", "zone_b"]

# §15.1's stated p95 targets, generously interpreted (this test measures
# one run, not a p95 over many) — a single run finishing well under these
# is the meaningful signal, not a statistically rigorous p95 measurement.
SIMPLE_RUN_TARGET_SECONDS = 30.0
INTRADAY_TARGET_SECONDS = 60.0


def _seed_capacity_scenario(session) -> None:
    for hours_back in range(4 * 24, 0, -1):
        session.add(
            DemandBucket(
                tenant_id="ten_test", activity="picking", site_id=SITE_ID, customer_id=None,
                interval_start=WINDOW_START - timedelta(hours=hours_back), volume=400.0, source="tempo_native",
            )
        )
    session.add(WorkStandard(tenant_id="ten_test", activity="picking", complexity_segment=None, time_per_unit_seconds=45.0, effective_from=WINDOW_START - timedelta(days=365)))
    session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id=SITE_ID, activity="picking", role="picker", zone="zone_a", weight=1.0))
    session.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id=SITE_ID, activity="picking", role="picker", zone="zone_b", weight=1.0))
    for labour_type, rate in [("permanent", "35.00"), ("casual", "32.00"), ("labour_hire", "45.00")]:
        session.add(
            LabourCostRule(
                tenant_id="ten_test", labour_type=labour_type, role="picker", rate=rate,
                overtime_multiplier="1.5", surcharge="10.00" if labour_type == "labour_hire" else None, currency="AUD",
            )
        )
    for i in range(NUM_WORKERS):
        employment_type = EMPLOYMENT_TYPES[i % len(EMPLOYMENT_TYPES)]
        session.add(Worker(worker_id=f"w{i}", tenant_id="ten_test", employment_type=employment_type, home_site=SITE_ID, status="active"))
        session.add(SkillCertification(tenant_id="ten_test", worker_id=f"w{i}", skill_code="picker", valid_from=WINDOW_START - timedelta(days=365), valid_to=None))
        session.add(
            ShiftAssignment(
                tenant_id="ten_test", worker_id=f"w{i}", role="picker", zone=ZONES[i % 2],
                start_at=WINDOW_START, end_at=WINDOW_START + timedelta(hours=8), status="committed",
            )
        )
        if i % 10 == 0:
            session.add(
                Availability(
                    tenant_id="ten_test", worker_id=f"w{i}",
                    interval_start=WINDOW_START, interval_end=WINDOW_START + timedelta(hours=8),
                    status="leave_requested", preference=0.5,
                )
            )
    session.add(ZoneBacklog(tenant_id="ten_test", site_id=SITE_ID, zone="zone_a", interval_start=WINDOW_START, backlog_units=50))
    session.add(ZoneBacklog(tenant_id="ten_test", site_id=SITE_ID, zone="zone_b", interval_start=WINDOW_START, backlog_units=0))
    for i in range(50):
        session.add(
            DemandBucket(
                tenant_id="ten_test", activity="picking", site_id=SITE_ID, customer_id=f"cust_{i % 10}",
                interval_start=WINDOW_START, volume=200.0, source="wms",
            )
        )
        session.add(
            SellRateContract(
                tenant_id="ten_test", customer_id=f"cust_{i % 10}", activity="picking", rate="5.00", currency="AUD",
                sla_penalty="2.00", effective_from=WINDOW_START - timedelta(days=30), effective_to=None,
            )
        )
    session.commit()


def _request() -> RunRequest:
    return RunRequest(
        request_id="req_capacity",
        scope=RunScope(tenant_id="ten_test", site_ids=[SITE_ID], customer_ids=["cust_A"]),
        planning_window=PlanningWindow(
            start=WINDOW_START, end=WINDOW_START + timedelta(days=NUM_DAYS), timezone="Australia/Melbourne", bucket_minutes=60
        ),
    )


def test_simple_run_solvers_meet_p95_target_at_pilot_scale(client):
    with client.session_local() as db:
        _seed_capacity_scenario(db)
        request = _request()

        for solver, name in [
            (solve_workforce_mix, "workforce_mix"),
            (solve_named_roster, "named_roster"),
            (solve_training_coverage, "training_coverage"),
            (solve_leave_rdo, "leave_rdo"),
            (solve_team_composition, "team_composition"),
        ]:
            start = time.monotonic()
            outcome = solver(db, "ten_test", [SITE_ID], request)
            elapsed = time.monotonic() - start
            assert outcome.result, f"{name} produced no result"
            assert elapsed < SIMPLE_RUN_TARGET_SECONDS, (
                f"{name} took {elapsed:.2f}s at {NUM_WORKERS} workers x {NUM_DAYS} days — "
                f"exceeds the §15.1 simple-run p95 target of {SIMPLE_RUN_TARGET_SECONDS:.0f}s"
            )


def test_intraday_reallocation_meets_p95_target_at_pilot_scale(client):
    with client.session_local() as db:
        _seed_capacity_scenario(db)
        request = _request()

        start = time.monotonic()
        outcome = solve_intraday_reallocation(db, "ten_test", [SITE_ID], request)
        elapsed = time.monotonic() - start

    assert outcome.result
    assert elapsed < INTRADAY_TARGET_SECONDS, (
        f"intraday_reallocation took {elapsed:.2f}s at {NUM_WORKERS} workers — "
        f"exceeds the §15.1 intraday p95 target of {INTRADAY_TARGET_SECONDS:.0f}s"
    )


def test_margin_3pl_and_scenario_complete_within_a_reasonable_bound(client):
    """Neither run_type gets its own row in §15.1's SLO table — margin_3pl
    is the same MILP class as workforce_mix/mix (30s target reasonably
    applies), and scenario's own row ("Progress within 10 seconds") is
    about async progress reporting this synchronous implementation doesn't
    do (see app/solvers/scenario.py's docstring) — so this holds both to
    the same 30s bound as a practical regression guard, not a literal
    reading of either spec row.
    """
    with client.session_local() as db:
        _seed_capacity_scenario(db)
        request = _request()

        for solver, name in [(solve_margin_3pl, "margin_3pl"), (solve_scenario, "scenario")]:
            start = time.monotonic()
            outcome = solver(db, "ten_test", [SITE_ID], request)
            elapsed = time.monotonic() - start
            assert outcome.result, f"{name} produced no result"
            assert elapsed < SIMPLE_RUN_TARGET_SECONDS, f"{name} took {elapsed:.2f}s — exceeds the {SIMPLE_RUN_TARGET_SECONDS:.0f}s bound"
