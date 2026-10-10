"""Arch completion pass acceptance tests: equipment shared across overlapping activities, congestion
integration, effective weekday (day) rates, function/flow preserved into results, award overtime,
and permanent-before-casual fill priority — exercised through the real run-creation path.
"""
from __future__ import annotations

import pytest

from .test_imports import MEL, admin, csv_text, seed, stage
from .test_integration_order_schedule import _body, _get, _order, _process, _rate, _run, _staff, _window
from .test_stage2_order_workload import apply as _apply_batch


def apply(client, h, b):
    return _apply_batch(client, h, b)


WINDOW = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")


def test_equipment_shared_across_two_different_activities_in_one_interval(client):
    """Priority 10: a pool is shared across DIFFERENT activities drawing on it concurrently, not
    independently re-granted the full pool to each."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1", "E2"])
    _rate(client, h, "E1", "picking", 100)
    _rate(client, h, "E2", "packing", 100)
    equip = csv_text(["site", "equipment_id", "description", "quantity_available"], [[MEL, "HIGH_REACH", "forklift", "1"]])
    apply(client, h, stage(client, h, "master", equip, entity="equipment").json())
    _process(client, h, "p_pick", [(1, "picking", 0, "HIGH_REACH", "")])
    _process(client, h, "p_put", [(1, "packing", 0, "HIGH_REACH", "")])
    _order(client, h, "SO-PICK", "2026-10-12 09:00", "2026-10-12 12:00", 500, "p_pick")
    _order(client, h, "SO-PUT", "2026-10-12 09:00", "2026-10-12 12:00", 500, "p_put")
    result = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert result["equipment_violations"] == []
    total_done = sum(o["quantity"] - o["shortfall_quantity"] for o in result["orders"])
    assert total_done == pytest.approx(300, abs=0.01)  # only ONE truck's worth of total throughput across BOTH activities


def test_congestion_reduces_capacity_in_an_integrated_run(client):
    """Priority 12: congestion is exercised through the real run path, not only the pure function."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")  # exactly 100/h * 3h with no congestion

    baseline = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert baseline["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.01)

    loss = csv_text(["site", "type", "percent_loss"], [[MEL, "congestion", "20"]])
    apply(client, h, stage(client, h, "master", loss, entity="productivity_loss").json())
    congested = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert congested["orders"][0]["shortfall_quantity"] > 0  # 20% slower now falls short of the same deadline


def test_effective_weekday_day_rate_changes_capacity(client):
    """Priority 15: a day rate measurably changes capacity for a worker with no personal rate."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])  # no personal rate — standard rate would otherwise apply
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")  # needs 100/h to clear in 3h
    before = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]  # seed()'s default standard: 45s/unit = 80/h

    day_rate = csv_text(["activity", "weekday", "rate_per_hour"], [["picking", "monday", "150"]])
    apply(client, h, stage(client, h, "master", day_rate, entity="day_rates").json())
    after = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert after["orders"][0]["shortfall_quantity"] < before["orders"][0]["shortfall_quantity"]  # the day rate's higher throughput changed the outcome


def test_function_and_flow_survive_import_into_results(client):
    """Priority 16: function/flow on a work standard are preserved through to scheduling results."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    ff = csv_text(["activity", "seconds_per_unit", "function", "flow"], [["picking", "36", "warehousing", "outbound"]])
    apply(client, h, stage(client, h, "master", ff, entity="work_standards").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p1")
    result = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    step = result["orders"][0]["steps"][0]
    assert step["function"] == "warehousing" and step["flow"] == "outbound"


def test_award_overtime_multiplier_applies_beyond_ordinary_daily_hours(client):
    """Priority 17: an award name alone does nothing until a matching AwardRule exists; once it
    does, hours beyond the ordinary threshold cost more."""
    seed(client)
    h = admin()
    staff = csv_text(["Employee ID", "Full Name", "Location", "Type", "Award"], [["E1", "Worker E1", MEL, "permanent", "retail_2024"]])
    apply(client, h, stage(client, h, "master", staff, entity="workers").json())
    _rate(client, h, "E1", "picking", 100)
    rate = csv_text(["employment_type", "role", "hourly_rate"], [["permanent", "picking", "40"]])
    apply(client, h, stage(client, h, "master", rate, entity="rates").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 06:00", "2026-10-12 16:00", 1000, "p1")  # a long window so the worker clocks up double-digit hours

    without_award = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]["kpis"]["total_cost"]

    award = csv_text(["award_code", "ordinary_hours_per_day", "overtime_multiplier"], [["retail_2024", "8", "1.5"]])
    apply(client, h, stage(client, h, "master", award, entity="award_rules").json())
    with_award = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]["kpis"]["total_cost"]
    assert with_award > without_award  # the same hours now cost more once overtime applies past 8h/day


def test_permanent_before_casual_fill_priority(client):
    """Priority 8: employment-type fill priority can express 'permanent before casual' — it is not
    a hardcoded rule, just a configured priority. Proven by cost: the two workers have different
    rates, so WHICH one gets picked when only one is needed is directly observable."""
    seed(client)
    h = admin()
    _staff(client, h, ["E_PERM"])
    casual = csv_text(["Employee ID", "Full Name", "Location", "Type"], [["E_CASUAL", "Casual Worker", MEL, "casual"]])
    apply(client, h, stage(client, h, "master", casual, entity="workers").json())
    _rate(client, h, "E_PERM", "picking", 50)
    _rate(client, h, "E_CASUAL", "picking", 50)  # same productivity rate — only the fill priority should decide who is picked
    perm_rate = csv_text(["employment_type", "role", "hourly_rate"], [["permanent", "picking", "40"]])
    casual_rate = csv_text(["employment_type", "role", "hourly_rate"], [["casual", "picking", "25"]])
    apply(client, h, stage(client, h, "master", perm_rate, entity="rates").json())
    apply(client, h, stage(client, h, "master", casual_rate, entity="rates").json())
    hc = csv_text(["site", "activity", "min_headcount", "max_headcount"], [[MEL, "picking", "0", "1"]])  # force a single-worker choice
    apply(client, h, stage(client, h, "master", hc, entity="headcount_limits").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 10, "p1")

    priorities = csv_text(["scope", "value", "priority"], [["employment_type", "permanent", "1"], ["employment_type", "casual", "2"]])
    apply(client, h, stage(client, h, "master", priorities, entity="fill_priorities").json())
    result = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert result["orders"][0]["on_time"] is True
    assert result["kpis"]["total_cost"] == pytest.approx(40, abs=0.5)  # one sub-interval's paid hour, at the PERMANENT worker's $40/h — not the casual's $25/h


def test_timezone_offset_string_is_normalized_instead_of_crashing(client):
    """A caller whose browser resolves its timezone to a raw UTC offset (seen in at least one
    headless environment) must not crash the scheduler with ZoneInfoNotFoundError."""
    from app.solvers.order_workload import _normalize_timezone_name
    assert _normalize_timezone_name("+00:00") == "UTC"
    assert _normalize_timezone_name("Australia/Melbourne") == "Australia/Melbourne"
    assert _normalize_timezone_name("+11:00") == "Etc/GMT-11"
    assert _normalize_timezone_name("-05:00") == "Etc/GMT+5"

    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p1")
    window = {"start": "2026-10-11T12:00:00Z", "end": "2026-10-13T12:00:00Z", "timezone": "+00:00", "bucket_minutes": 60}
    run = _run(client, _body(window))
    assert run["status"] in ("completed", "completed_with_warnings")
