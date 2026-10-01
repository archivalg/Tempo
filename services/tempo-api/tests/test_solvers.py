"""Solver-level tests — check the actual mathematical properties the AI
Labour Optimisation Spec requires, not just that the API plumbing works.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from app.core.policy import DEFAULT_CONSTRAINTS
from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.demand_forecast import forecast_demand
from app.solvers.named_roster import solve_named_roster
from app.solvers.workforce_mix import INTERNAL_TYPES, solve_workforce_mix
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
        assert internal >= DEFAULT_CONSTRAINTS["internal_min_ratio"] * total - 1e-6, f"{day}: internal ratio breached"
        assert hire <= DEFAULT_CONSTRAINTS["hire_max_ratio"] * total + 1e-6, f"{day}: hire ratio breached"


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


def _daily_history(db, weeks: int, weekday_mult: dict[int, float]):
    """`weeks` of daily buckets ending the day before WINDOW_START (Mon 2026-09-07 local), with a known weekly shape and a gentle trend."""
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    from app.models.canonical import DemandBucket
    tz = ZoneInfo("Australia/Melbourne")
    end = datetime(2026, 9, 8, tzinfo=tz)
    for i in range(weeks * 7, 0, -1):
        d = end - timedelta(days=i)
        base = 1000 + 2 * (weeks * 7 - i)
        db.add(DemandBucket(tenant_id="ten_test", activity="picking", site_id="site_mel_01", interval_start=d.astimezone(timezone.utc), volume=base * weekday_mult[d.weekday()],
                            source="test", bucket_minutes=1440))
    db.commit()


def _daily_request() -> RunRequest:
    from zoneinfo import ZoneInfo
    s = datetime(2026, 9, 8, tzinfo=ZoneInfo("Australia/Melbourne")).astimezone(timezone.utc)
    from datetime import timedelta
    return RunRequest(request_id="req_s", scope=RunScope(tenant_id="ten_test", site_ids=["site_mel_01"], customer_ids=["cust_A"]),
                      planning_window=PlanningWindow(start=s, end=s + timedelta(days=7), timezone="Australia/Melbourne", bucket_minutes=1440))


SHAPE = {0: 1.3, 1: 1.2, 2: 1.1, 3: 1.0, 4: 0.9, 5: 0.35, 6: 0.15}  # busy early week, near-empty weekend


def test_weekly_pattern_is_learned_with_two_or_more_weeks_and_beats_trend_only(client):
    with client.session_local() as db:
        _daily_history(db, 6, SHAPE)
        with_pattern = forecast_demand(db, "ten_test", ["site_mel_01"], _daily_request())
    assert with_pattern.result["method"] == "holt_linear_weekly" and with_pattern.result["seasonality"]["weekly_applied_to"] == ["picking"]
    from zoneinfo import ZoneInfo
    rows = {datetime.fromisoformat(r["bucket_start"]).astimezone(ZoneInfo("Australia/Melbourne")).weekday(): r["point"] for r in with_pattern.result["forecast"]}
    assert rows[6] < rows[5] < rows[4] < rows[1] < rows[0] * 1.001           # Sunday lowest, then Saturday, then the working week
    base = 1000 + 2 * 42
    for dow, mult in SHAPE.items():                                          # each day within ~12% of truth (the trend is only approximated)
        assert abs(rows[dow] - base * mult) / (base * mult) < 0.12, (dow, rows[dow], base * mult)
    assert with_pattern.result["backtest_mape"] < 0.10


def test_under_two_weeks_falls_back_to_trend_only_and_says_so(client):
    with client.session_local() as db:
        _daily_history(db, 1, SHAPE)
        out = forecast_demand(db, "ten_test", ["site_mel_01"], _daily_request())
    assert out.result["method"] == "holt_linear" and out.result["seasonality"]["no_pattern_for"] == ["picking"]
    assert any("under two weeks" in m for m in out.missing_evidence)
