"""Solver-level tests — check the actual mathematical properties the AI
Labour Optimisation Spec requires, not just that the API plumbing works.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.demand_forecast import forecast_demand
from app.solvers.named_roster import solve_named_roster
from app.solvers.workforce_mix import DEFAULT_HIRE_MAX_RATIO, DEFAULT_INTERNAL_MIN_RATIO, INTERNAL_TYPES, solve_workforce_mix
from .factories import seed_named_roster_scenario

WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)


def _request() -> RunRequest:
    return RunRequest(
        request_id="req_test",
        scope=RunScope(tenant_id="ten_test", site_ids=["site_mel_01"], customer_ids=["cust_A"]),
        planning_window=PlanningWindow(
            start=WINDOW_START,
            end=datetime(2026, 9, 15, tzinfo=timezone.utc),
            timezone="Australia/Melbourne",
            bucket_minutes=60,
        ),
    )


def _seeded_session(client):
    with client.session_local() as session:
        seed_named_roster_scenario(session, tenant_id="ten_test", site_id="site_mel_01", window_start=WINDOW_START)
    return client.session_local()


def test_forecast_covers_the_full_horizon(client):
    with client.session_local() as seed_session:
        seed_named_roster_scenario(seed_session, tenant_id="ten_test", site_id="site_mel_01", window_start=WINDOW_START)
    with client.session_local() as db:
        outcome = forecast_demand(db, "ten_test", ["site_mel_01"], _request())
    assert len(outcome.result["forecast"]) == 7 * 24  # hourly buckets over a 7-day window
    assert all(row["point"] >= 0 for row in outcome.result["forecast"])


def test_workforce_mix_never_breaches_hire_ratio(client):
    with client.session_local() as seed_session:
        seed_named_roster_scenario(seed_session, tenant_id="ten_test", site_id="site_mel_01", window_start=WINDOW_START)
    with client.session_local() as db:
        outcome = solve_workforce_mix(db, "ten_test", ["site_mel_01"], _request())

    by_day: dict[str, Counter] = {}
    for a in outcome.result["assignments"]:
        by_day.setdefault(a["day"], Counter())[a["employment_type"]] += a["headcount"]
    for day, counts in by_day.items():
        total = sum(counts.values())
        internal = sum(n for etype, n in counts.items() if etype in INTERNAL_TYPES)
        hire = sum(n for etype, n in counts.items() if etype == "labour_hire")
        if total == 0:
            continue
        assert internal >= DEFAULT_INTERNAL_MIN_RATIO * total - 1e-6, f"{day}: internal ratio breached"
        assert hire <= DEFAULT_HIRE_MAX_RATIO * total + 1e-6, f"{day}: hire ratio breached"


def test_named_roster_never_double_books_a_worker_on_one_day(client):
    with client.session_local() as seed_session:
        seed_named_roster_scenario(seed_session, tenant_id="ten_test", site_id="site_mel_01", window_start=WINDOW_START)
    with client.session_local() as db:
        outcome = solve_named_roster(db, "ten_test", ["site_mel_01"], _request())

    seen: set[tuple[str, str]] = set()
    for a in outcome.result["assignments"]:
        key = (a["worker_id"], a["day"])
        assert key not in seen, f"worker {a['worker_id']} double-booked on {a['day']}"
        seen.add(key)
