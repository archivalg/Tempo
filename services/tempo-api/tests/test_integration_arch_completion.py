"""Arch completion pass acceptance tests: equipment shared across overlapping activities, congestion
integration, effective weekday (day) rates, function/flow preserved into results, award overtime,
and permanent-before-casual fill priority — exercised through the real run-creation path.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from .test_imports import MEL, admin, csv_text, seed, stage
from .test_integration_order_schedule import _body, _get, _order, _process, _rate, _run, _shift, _staff, _window
from .test_stage2_order_workload import apply as _apply_batch


def apply(client, h, b):
    return _apply_batch(client, h, b)


WINDOW = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")


def _body_committed(window):
    b = _body(window)
    b["input"] = {"committed": True}
    return b


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


# --------------------------------------------------------------------------------------------- 1. open backlog
def test_committed_run_carries_open_backlog_forward_without_duplication(client):
    """Priority 1: a committed run that cannot finish an order persists how much it actually
    completed; a LATER committed run (here, after the customer extends the deadline) only schedules
    what is left — the two runs' combined output equals the order's quantity exactly, never more."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 1000, "p1")  # 100/h * 3h = 300 achievable in this first window

    first = _get(client, _run(client, _body_committed(WINDOW))["run_id"])["result"]
    assert first["orders"][0]["quantity"] == pytest.approx(1000, abs=0.01)
    assert first["orders"][0]["shortfall_quantity"] == pytest.approx(700, abs=0.5)
    produced_first = first["orders"][0]["quantity"] - first["orders"][0]["shortfall_quantity"]

    with client.session_local() as s:
        from app.models.orders import Order
        o = s.scalar(select(Order).where(Order.tenant_id == "ten_test", Order.site_id == MEL, Order.order_ref == "SO-1"))
        assert o.status == "open"
        assert o.fulfilled_units == pytest.approx(produced_first, abs=0.5)

    # The customer extends the deadline into a LATER, non-overlapping window — a second committed run
    # for the SAME window would be a conflicting double-commitment (app.api.v1.runs._check_committed_conflict)
    # and is correctly refused; a later window is the realistic way a backlog actually gets carried forward.
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-15 09:00", 1000, "p1")
    window2 = _window("2026-10-13T12:00:00Z", "2026-10-16T12:00:00Z")
    second = _get(client, _run(client, _body_committed(window2))["run_id"])["result"]
    assert second["orders"][0]["quantity"] == pytest.approx(1000 - produced_first, abs=0.5)  # only the BACKLOG, not the whole order again
    assert second["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)
    produced_second = second["orders"][0]["quantity"] - second["orders"][0]["shortfall_quantity"]

    assert produced_first + produced_second == pytest.approx(1000, abs=0.5)  # no duplication, no shortfall overall
    with client.session_local() as s:
        from app.models.orders import Order
        o = s.scalar(select(Order).where(Order.tenant_id == "ten_test", Order.site_id == MEL, Order.order_ref == "SO-1"))
        assert o.status == "completed"
        assert o.fulfilled_units == pytest.approx(1000, abs=0.5)


def test_draft_run_never_persists_backlog_or_completes_an_order(client):
    """Priority 1: a draft (the default, committed=False) promises nothing — it must not shrink what
    a real run still owes, no matter what it scheduled on paper."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")  # fully achievable in one run
    draft = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert draft["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)  # the draft itself "succeeds"...

    with client.session_local() as s:
        from app.models.orders import Order
        o = s.scalar(select(Order).where(Order.tenant_id == "ten_test", Order.site_id == MEL, Order.order_ref == "SO-1"))
        assert o.status == "open" and o.fulfilled_units == 0.0  # ...but nothing was actually committed to the real backlog

    # A second draft sees the SAME full quantity again — nothing was consumed by the first draft.
    again = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert again["orders"][0]["quantity"] == pytest.approx(300, abs=0.01)


# --------------------------------------------------------------------------------------------- 2. indirect coverage relief succeeds
def test_indirect_relief_worker_maintains_coverage_without_double_booking(client):
    """Priority 3: when a second qualified worker is available, break relief is proven to succeed (no
    indirect_coverage_gaps entry) — and that second worker remains free to do direct work in the SAME
    interval, proving the two roles are never double-booked onto one person."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1", "E2"])
    both_supervisors = csv_text(["Employee ID", "Full Name", "Location", "Type", "Skills"],
                                 [["E1", "Worker E1", MEL, "permanent", "supervisor"], ["E2", "Worker E2", MEL, "permanent", "supervisor"]])
    apply(client, h, stage(client, h, "master", both_supervisors, entity="workers").json())
    _rate(client, h, "E1", "picking", 100)  # same rate as E2 — whichever of them gets picked for indirect coverage
    _rate(client, h, "E2", "picking", 100)  # (an internal detail), the OTHER one's direct-work throughput is deterministic
    _shift(client, h, "day", "06:00", "14:00", "monday", breaks=[(120, 20, True)])  # a break, so relief is actually asked for
    indirect = csv_text(["site", "role", "weekday", "start_time", "end_time", "headcount"], [[MEL, "supervisor", "monday", "06:00", "14:00", "1"]])
    apply(client, h, stage(client, h, "master", indirect, entity="indirect_headcount").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 06:00", "2026-10-12 14:00", 700, "p1")  # within the free worker's own ~7.67h productive capacity
    result = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]

    assert result["indirect_coverage_gaps"] == []  # relief succeeded — a qualified second worker was available
    assert result["kpis"]["indirect_paid_hours"] == pytest.approx(8.0, abs=0.01)  # exactly ONE worker's shift, not two — no double-booking into indirect coverage
    assert result["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=1.0)  # the OTHER worker, never reserved, was free to do direct work


# --------------------------------------------------------------------------------------------- 3. personal weekday windows, incl. overnight
def test_personal_weekday_window_rejects_outside_shift_but_admits_matching_overnight_shift(client):
    """Priority 5: enforced through the real run path, not only the pure function — including the
    overnight-boundary case, where the worker's own permitted window crosses midnight."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    pattern = csv_text(["worker_ref", "weekday", "available", "earliest_start", "latest_finish"], [["E1", "monday", "true", "22:00", "06:00"]])
    apply(client, h, stage(client, h, "master", pattern, entity="weekly_availability").json())
    _shift(client, h, "day", "09:00", "17:00", "monday")    # entirely outside E1's permitted window
    _shift(client, h, "night", "22:00", "06:00", "monday")  # exactly matches it (same overnight boundary)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-DAY", "2026-10-12 09:00", "2026-10-12 17:00", 400, "p1")
    _order(client, h, "SO-NIGHT", "2026-10-12 22:00", "2026-10-13 06:00", 400, "p1")
    window = _window("2026-10-11T12:00:00Z", "2026-10-14T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])["result"]
    by_ref = {o["order_ref"]: o for o in result["orders"]}
    assert by_ref["SO-DAY"]["shortfall_quantity"] == pytest.approx(400, abs=0.01)   # rejected entirely — outside E1's window
    assert by_ref["SO-NIGHT"]["shortfall_quantity"] == pytest.approx(0, abs=1.0)    # admitted — fully inside it, including across midnight


# --------------------------------------------------------------------------------------------- 4. headcount and dependencies
def test_minimum_headcount_violation_is_reported_through_a_real_run(client):
    """Priority 9: a minimum-headcount shortfall is a persisted, visible outcome of a real run, not
    only the pure check function."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    hc = csv_text(["site", "activity", "min_headcount", "max_headcount"], [[MEL, "picking", "2", "5"]])  # needs 2, only 1 worker exists
    apply(client, h, stage(client, h, "master", hc, entity="headcount_limits").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p1")
    result = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert len(result["headcount_violations"]) > 0
    assert result["headcount_violations"][0]["min_headcount"] == 2 and result["headcount_violations"][0]["assigned"] == 1


def test_process_step_duplicate_sequence_is_rejected_not_silently_ambiguous(client):
    """Priority 11: the process-step model is a strictly ordered integer sequence per template, which
    cannot structurally form a dependency cycle — the one way an upload could still create an
    ambiguous ("which comes next?") ordering is two rows claiming the SAME sequence number in one
    file, and that is rejected at import, not silently resolved by picking one."""
    seed(client)
    h = admin()
    apply(client, h, stage(client, h, "master", csv_text(["site", "process_code", "customer_id"], [[MEL, "p1", ""]]), entity="process_templates").json())
    dup = csv_text(["site", "process_code", "sequence", "activity"], [[MEL, "p1", "1", "picking"], [MEL, "p1", "1", "packing"]])
    staged = stage(client, h, "master", dup, entity="process_steps").json()
    assert staged["error_rows"] == 1  # the second row duplicates the first's (site, process_code, sequence) key


# --------------------------------------------------------------------------------------------- 5. operating calendars revalidated at scheduling time
def test_operating_hours_conflict_excludes_shift_but_preserves_compliant_capacity(client):
    """Priority 5 (brief's calendar item): revalidated at SCHEDULING time, every run — not only at
    shift-template import time — so a calendar edited after the fact is still caught."""
    seed(client)
    h = admin()
    cal = csv_text(["site", "weekday", "is_24h", "is_closed", "open_time", "close_time"], [[MEL, "monday", "false", "false", "06:00", "14:00"]])
    apply(client, h, stage(client, h, "master", cal, entity="operating_calendar").json())
    _shift(client, h, "day", "06:00", "14:00", "monday")    # within operating hours
    _shift(client, h, "late", "12:00", "20:00", "monday")   # extends 6h past close — a conflict
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 06:00", "2026-10-12 14:00", 600, "p1")  # the compliant 'day' shift alone covers this (8h * 100/h = 800)
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])["result"]
    violations = result["operating_hours_violations"]
    assert any(v["shift_code"] == "late" for v in violations)
    assert not any(v["shift_code"] == "day" for v in violations)
    assert result["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)  # the compliant shift alone still fully covers it


def test_overnight_operating_hours_admit_a_matching_shift_and_exclude_a_conflicting_one(client):
    """Priority 5: the overnight-boundary case specifically — an operating window crossing midnight
    must correctly ADMIT a shift that fits it and still EXCLUDE one that does not."""
    seed(client)
    h = admin()
    cal = csv_text(["site", "weekday", "is_24h", "is_closed", "open_time", "close_time"], [[MEL, "monday", "false", "false", "22:00", "06:00"]])
    apply(client, h, stage(client, h, "master", cal, entity="operating_calendar").json())
    _shift(client, h, "night", "22:00", "06:00", "monday")  # exactly matches the overnight operating window
    _shift(client, h, "day", "09:00", "17:00", "monday")    # entirely outside it
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 22:00", "2026-10-13 06:00", 600, "p1")
    window = _window("2026-10-11T12:00:00Z", "2026-10-14T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])["result"]
    violations = result["operating_hours_violations"]
    assert any(v["shift_code"] == "day" for v in violations)
    assert not any(v["shift_code"] == "night" for v in violations)
    assert result["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)  # the overnight shift, fully inside operating hours, still delivers


# --------------------------------------------------------------------------------------------- 6. award/eligibility scope
def test_required_skill_excludes_unqualified_worker_with_explanation(client):
    """Priority 6/17: a qualification check (required_skill on the work standard), separate from any
    award restriction — an unqualified worker is excluded and the reason is explicit, not inferred."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1", "E2"])
    skilled = csv_text(["Employee ID", "Full Name", "Location", "Type", "Skills"], [["E2", "Worker E2", MEL, "permanent", "forklift_licence"]])
    apply(client, h, stage(client, h, "master", skilled, entity="workers").json())
    std = csv_text(["activity", "seconds_per_unit", "required_skill"], [["picking", "36", "forklift_licence"]])
    apply(client, h, stage(client, h, "master", std, entity="work_standards").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")  # exactly one worker's capacity (100/h * 3h)
    run = _get(client, _run(client, _body(WINDOW))["run_id"])
    assert run["result"]["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)  # E2 alone covers it
    assert any("E1" in m and "forklift_licence" in m for m in run["explanation"]["missing_evidence"])


def test_award_restricted_worker_is_excluded_with_explanation_not_inferred(client):
    """Priority 6/17: an EXPLICIT, imported award/activity restriction excludes a worker — never
    inferred from the award's own name. A worker under an unrestricted award is unaffected."""
    seed(client)
    h = admin()
    restricted = csv_text(["Employee ID", "Full Name", "Location", "Type", "Award"], [["E1", "Worker E1", MEL, "permanent", "junior_award"]])
    apply(client, h, stage(client, h, "master", restricted, entity="workers").json())
    unrestricted = csv_text(["Employee ID", "Full Name", "Location", "Type", "Award"], [["E2", "Worker E2", MEL, "permanent", "senior_award"]])
    apply(client, h, stage(client, h, "master", unrestricted, entity="workers").json())
    _rate(client, h, "E1", "picking", 100)
    _rate(client, h, "E2", "picking", 100)
    restriction = csv_text(["award_code", "activity"], [["junior_award", "picking"]])
    apply(client, h, stage(client, h, "master", restriction, entity="award_eligibility_restrictions").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")  # exactly one worker's capacity
    run = _get(client, _run(client, _body(WINDOW))["run_id"])
    assert run["result"]["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)  # E2 (senior_award) alone covers it
    assert any("E1" in m and "junior_award" in m for m in run["explanation"]["missing_evidence"])


def test_award_with_no_restriction_row_restricts_nothing(client):
    """Priority 6: an award with NO configured restriction row must not block anything — nothing is
    ever inferred from the award's name or pattern."""
    seed(client)
    h = admin()
    staff = csv_text(["Employee ID", "Full Name", "Location", "Type", "Award"], [["E1", "Worker E1", MEL, "permanent", "junior_award"]])
    apply(client, h, stage(client, h, "master", staff, entity="workers").json())
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    result = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert result["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)  # no restriction row exists for 'junior_award' — nothing is blocked
