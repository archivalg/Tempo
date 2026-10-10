"""Order-driven-planning integration increment: solve_order_fulfillment as one coherent plan,
exercised through the real run-creation path. Proves the specific behaviours requested:

1. Changing a constraint changes assignments/capacity/completion/cost.
2. Workers and equipment cannot be double-booked across overlapping tasks or shifts.
3. Direct work cannot consume time allocated to indirect coverage.
4. Breaks, absenteeism and productivity losses are not deducted twice.
5. Order dependencies and staging limits affect completion feasibility.
6. Missing inputs produce clear warnings or validation failures.
7. Infeasible runs remain persisted with actionable reasons (any run_type, not just the two
   originally fixed — see tests/test_run_infeasibility.py).
"""
from __future__ import annotations

import uuid

import pytest

import app.api.v1.runs as runs_module
from app.solvers.base import SolverInfeasible

from .conftest import context_header
from .test_imports import MEL, admin, csv_text, seed, stage
from .test_run_endpoint import _headers


def apply(client, h, b):
    r = client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def _run(client, body):
    r = client.post("/v1/optimisations/order_fulfillment", json=body, headers=_headers())
    assert r.status_code == 202, r.text
    return r.json()


def _get(client, run_id):
    return client.get(f"/v1/runs/{run_id}", headers=context_header()).json()


def _window(start, end, tz="Australia/Melbourne"):
    return {"start": start, "end": end, "timezone": tz, "bucket_minutes": 60}


def _body(window):
    return {"request_id": str(uuid.uuid4()), "scope": {"tenant_id": "ten_test", "site_ids": [MEL], "customer_ids": ["cust_A"]}, "planning_window": window}


def _staff(client, h, refs: list[str]):
    rows = [[r, f"Worker {r}", MEL, "permanent"] for r in refs]
    apply(client, h, stage(client, h, "master", csv_text(["Employee ID", "Full Name", "Location", "Type"], rows), entity="workers").json())


def _rate(client, h, worker_ref: str, activity: str, rate: float):
    apply(client, h, stage(client, h, "master", csv_text(["worker_ref", "activity", "rate_per_hour"], [[worker_ref, activity, str(rate)]]), entity="worker_activity_rates").json())


def _process(client, h, code: str, steps: list[tuple[int, str, int, str, str]]):
    """steps: (sequence, activity, lag_minutes, equipment_id, zone_id)"""
    apply(client, h, stage(client, h, "master", csv_text(["site", "process_code", "customer_id"], [[MEL, code, ""]]), entity="process_templates").json())
    rows = [[MEL, code, str(seq), act, str(lag), eq, zone] for seq, act, lag, eq, zone in steps]
    apply(client, h, stage(client, h, "master", csv_text(["site", "process_code", "sequence", "activity", "lag_minutes", "equipment_id", "zone_id"], rows), entity="process_steps").json())


def _order(client, h, order_id: str, received: str, due: str, units: float, process_code: str):
    r = apply(client, h, stage(client, h, "master", csv_text(["site", "order_id", "order_received", "despatch_due", "units", "process_code"],
                                                             [[MEL, order_id, received, due, str(units), process_code]]), entity="orders").json())
    return r


def _shift(client, h, code: str, start: str, end: str, weekdays: str, breaks: list[tuple[int, int, bool]] = ()):
    apply(client, h, stage(client, h, "master", csv_text(["site", "shift_code", "start_time", "end_time", "weekdays"], [[MEL, code, start, end, weekdays]]), entity="shift_templates").json())
    for offset, duration, paid in breaks:
        apply(client, h, stage(client, h, "master", csv_text(["site", "shift_code", "starts_after_minutes", "duration_minutes", "is_paid"], [[MEL, code, str(offset), str(duration), str(paid).lower()]]), entity="shift_breaks").json())


# --------------------------------------------------------------------------------------------- 1. a constraint changes the plan
def test_headcount_limit_changes_capacity_and_shortfall(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1", "E2"])
    _rate(client, h, "E1", "picking", 100)
    _rate(client, h, "E2", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 500, "p1")  # needs 500/200/h = 2.5h with both workers
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")

    uncapped = _get(client, _run(client, _body(window))["run_id"])
    assert uncapped["result"]["kpis"]["total_shortfall_quantity"] == 0  # both workers: 200 units/h * 3h window = 600 >= 500

    hc = csv_text(["site", "activity", "min_headcount", "max_headcount"], [[MEL, "picking", "0", "1"]])
    apply(client, h, stage(client, h, "master", hc, entity="headcount_limits").json())
    capped = _get(client, _run(client, _body(window))["run_id"])
    assert capped["result"]["kpis"]["total_shortfall_quantity"] > 0  # one worker: 100 units/h * 3h = 300 < 500 — the constraint changed the outcome


# --------------------------------------------------------------------------------------------- 2. no double-booking (workers, equipment)
def test_one_worker_shared_across_two_orders_is_never_double_counted(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    # Two orders, same window, same single worker: total served cannot exceed one worker's output.
    _order(client, h, "SO-A", "2026-10-12 09:00", "2026-10-12 12:00", 200, "p1")
    _order(client, h, "SO-B", "2026-10-12 09:00", "2026-10-12 12:00", 200, "p1")
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])["result"]
    total_done = sum(o["quantity"] - o["shortfall_quantity"] for o in result["orders"])
    assert total_done == pytest.approx(300, abs=0.01)  # 100 units/h * 3h = 300 total capacity, however it's split between the two orders
    assert result["kpis"]["total_shortfall_quantity"] == pytest.approx(100, abs=0.01)


def test_equipment_pool_of_one_is_never_double_booked_across_two_orders(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1", "E2"])
    _rate(client, h, "E1", "picking", 100)
    _rate(client, h, "E2", "picking", 100)
    equip = csv_text(["site", "equipment_id", "description", "quantity_available"], [[MEL, "HIGH_REACH", "forklift", "1"]])
    apply(client, h, stage(client, h, "master", equip, entity="equipment").json())
    _process(client, h, "p1", [(1, "picking", 0, "HIGH_REACH", "")])
    _order(client, h, "SO-A", "2026-10-12 09:00", "2026-10-12 12:00", 500, "p1")
    _order(client, h, "SO-B", "2026-10-12 09:00", "2026-10-12 12:00", 500, "p1")
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])["result"]
    assert result["equipment_violations"] == []  # the cap was respected, not merely reported after the fact
    total_done = sum(o["quantity"] - o["shortfall_quantity"] for o in result["orders"])
    assert total_done == pytest.approx(300, abs=0.01)  # only ONE worker's throughput (equipment-capped), not both workers' 600


# --------------------------------------------------------------------------------------------- 3. indirect coverage is exclusive of direct work
def test_worker_reserved_for_indirect_coverage_cannot_also_do_direct_work(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    skill = csv_text(["Employee ID", "Full Name", "Location", "Type", "Skills"], [["E1", "Worker E1", MEL, "permanent", "supervisor"]])
    apply(client, h, stage(client, h, "master", skill, entity="workers").json())  # adds the 'supervisor' skill to the same worker
    indirect = csv_text(["site", "role", "weekday", "start_time", "end_time", "headcount"], [[MEL, "supervisor", "monday", "00:00", "23:59", "1"]])
    apply(client, h, stage(client, h, "master", indirect, entity="indirect_headcount").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p1")
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])["result"]
    assert result["indirect_coverage_gaps"] == []  # the one worker fully covers the indirect requirement
    assert result["orders"][0]["shortfall_quantity"] == pytest.approx(100, abs=0.01)  # and so has zero time left for direct picking
    assert result["orders"][0]["steps"][0]["shortfall_reason"] in ("missing_skill", "deadline_breach")


# --------------------------------------------------------------------------------------------- 4. no double-deduction of breaks / off-task / absenteeism
def test_breaks_off_task_and_absenteeism_each_apply_exactly_once(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _shift(client, h, "day", "06:00", "14:00", "monday", breaks=[(120, 20, True), (240, 30, False)])
    # elapsed 480min; paid break 20 + unpaid 30 → paid_hours=7.5h, productive_hours=(480-30-20)/60=7.1667h
    loss = csv_text(["site", "type", "off_task_hours"], [[MEL, "off_task", "0.5"]])
    apply(client, h, stage(client, h, "master", loss, entity="productivity_loss").json())
    absenteeism = csv_text(["site", "activity", "absence_pct"], [[MEL, "picking", "10"]])
    apply(client, h, stage(client, h, "master", absenteeism, entity="absenteeism").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    # effective_hours = 7.1667 - 0.5 = 6.6667h; effective_rate = 100 * 0.9 = 90/h → capacity = 600.00 units exactly
    _order(client, h, "SO-1", "2026-10-12 06:00", "2026-10-12 14:00", 600, "p1")
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])["result"]
    # If any loss were deducted twice, capacity would undershoot 600 and this would show a shortfall.
    assert result["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)
    assert result["kpis"]["total_paid_hours"] == pytest.approx(7.5, abs=0.01)  # paid hours are NOT reduced by off-task loss
    assert result["kpis"]["total_productive_hours"] == pytest.approx(7.1667 - 0.5, abs=0.01)  # off-task applied once, on top of (not instead of) the break deduction


# --------------------------------------------------------------------------------------------- 5. dependencies and staging affect feasibility
def test_pack_cannot_start_before_its_own_orders_pick_completes(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 1000)
    _rate(client, h, "E1", "packing", 1000)
    _process(client, h, "p1", [(1, "picking", 0, "", ""), (2, "packing", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-13 09:00", 100, "p1")
    window = _window("2026-10-11T12:00:00Z", "2026-10-14T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])["result"]
    pick, pack = result["orders"][0]["steps"]
    assert pick["completed_at"] is not None
    assert pack["release_at"] is None or pack["completed_at"] is None or pack["release_at"] >= pick["completed_at"]
    if pack["completed_at"]:
        assert pack["completed_at"] >= pick["completed_at"]


def test_staging_capacity_with_no_relief_holds_the_order_back_entirely(client):
    """A single-shot 100-unit completion into a 50-unit zone that never empties is never forced to
    overflow — it is held back every time, so the whole order remains an honest, reported shortfall."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "packing", 1000)
    zones = csv_text(["site", "zone_id", "zone_name"], [[MEL, "STAGE", "Staging"]])
    apply(client, h, stage(client, h, "master", zones, entity="zones").json())
    cap = csv_text(["site", "zone_id", "capacity", "unit"], [[MEL, "STAGE", "50", "units"]])
    apply(client, h, stage(client, h, "master", cap, entity="staging_capacity").json())
    _process(client, h, "p1", [(1, "packing", 0, "", "STAGE")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p1")  # 100 units arrive into a 50-unit zone
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])
    assert result["result"]["staging_delays"], "the step must be held back, not force-completed into a full zone"
    assert result["result"]["orders"][0]["shortfall_quantity"] == pytest.approx(100, abs=0.01)
    assert result["explanation"]["feasibility"] == "feasible_with_slack"  # attempted (the worker was assigned), not "no plan found"


def test_staging_capacity_delays_completion_until_a_departure_frees_room(client):
    """Priority 3: staging capacity should delay upstream work and let it complete once room frees
    up, rather than only ever reporting an unavoidable shortfall."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "packing", 1000)
    zones = csv_text(["site", "zone_id", "zone_name"], [[MEL, "STAGE", "Staging"]])
    apply(client, h, stage(client, h, "master", zones, entity="zones").json())
    cap = csv_text(["site", "zone_id", "capacity", "unit"], [[MEL, "STAGE", "100", "units"]])
    apply(client, h, stage(client, h, "master", cap, entity="staging_capacity").json())
    movements = csv_text(["site", "zone_id", "occurred_at", "movement_type", "quantity", "unit"],
                         [[MEL, "STAGE", "2026-10-11 00:00", "initial", "60", "units"], [MEL, "STAGE", "2026-10-12 10:30", "departure", "60", "units"]])
    apply(client, h, stage(client, h, "master", movements, entity="staging_movements").json())
    _process(client, h, "p1", [(1, "packing", 0, "", "STAGE")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p1")  # needs the full 100-unit zone; only free after the 10:30 departure
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    result = _get(client, _run(client, _body(window))["run_id"])
    assert result["result"]["staging_delays"], "earlier sub-intervals must be held back until the departure frees room"
    assert result["result"]["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.01)  # but it completes once room frees up
    assert result["result"]["orders"][0]["on_time"] is True


# --------------------------------------------------------------------------------------------- 6. missing inputs produce clear warnings
def test_zero_workers_at_site_is_proven_infeasible_not_a_silent_warning(client):
    """No worker exists at all, so the scheduler never manages to assign anyone to anything — this
    is "no plan found", not an ordinary partial shortfall (priority 1)."""
    seed(client)  # "picking" has a work standard, but there is no worker at the site at all
    h = admin()
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p1")
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    run = _run(client, _body(window))
    assert run["status"] == "failed"
    result = _get(client, run["run_id"])
    assert result["explanation"]["feasibility"] == "infeasible"
    assert "no feasible allocation" in result["explanation"]["primary_drivers"][0]


def test_one_order_blocked_by_configuration_warns_without_failing_the_whole_run(client):
    """A second, unaffected order proves this is a clear, attributable warning on one demand line —
    not every missing/blocking input makes the whole run infeasible (priority 1 vs. ordinary shortfall)."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1", "E2"])  # dedicated workers so neither activity contends with the other for the same person
    _rate(client, h, "E1", "picking", 100)
    _rate(client, h, "E2", "packing", 100)
    hc = csv_text(["site", "activity", "min_headcount", "max_headcount"], [[MEL, "picking", "0", "0"]])  # explicitly configured to allow nobody
    apply(client, h, stage(client, h, "master", hc, entity="headcount_limits").json())
    _process(client, h, "p_pick", [(1, "picking", 0, "", "")])
    _process(client, h, "p_pack", [(1, "packing", 0, "", "")])
    _order(client, h, "SO-PICK", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p_pick")
    _order(client, h, "SO-PACK", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p_pack")
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    run = _run(client, _body(window))
    assert run["status"] == "completed_with_warnings"
    result = _get(client, run["run_id"])
    assert any("no capacity available for activity 'picking'" in m for m in result["explanation"]["missing_evidence"])
    by_ref = {o["order_ref"]: o for o in result["result"]["orders"]}
    assert by_ref["SO-PICK"]["steps"][0]["shortfall_reason"] in ("headcount_cap", "missing_skill")  # both are legitimate, reported reasons the cap produces across sub-intervals
    assert by_ref["SO-PACK"]["on_time"] is True  # the other order is unaffected


# --------------------------------------------------------------------------------------------- 7. infeasible runs persist with actionable reasons
def test_infeasible_order_fulfillment_run_persists_with_a_reason(client, monkeypatch):
    seed(client)
    h = admin()

    def _boom(db, tenant_id, site_ids, request):
        raise SolverInfeasible("order fulfillment scheduler found no feasible allocation for this scope and window")

    monkeypatch.setitem(runs_module._SOLVERS, "order_fulfillment", _boom)
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    run = _run(client, _body(window))
    assert run["status"] == "failed"
    result = _get(client, run["run_id"])
    assert result["status"] == "failed"
    assert result["explanation"]["feasibility"] == "infeasible"
    assert "no feasible allocation" in result["explanation"]["primary_drivers"][0]
