"""Order-driven-planning Stage 2 acceptance scenarios (docs/order-driven-planning.md):
deadline planning, process flow precedence, personal rates, unit conversion.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.orders import Order, ProcessStep, ProcessTemplate, UnitConversion, WorkerActivityRate
from app.solvers.order_workload import (
    WorkerCapacity,
    plan_order_steps,
    resolve_activity_rate,
    resolve_order_quantity,
    schedule_activity,
)

from .conftest import context_header
from .test_imports import MEL, admin, csv_text, seed, stage
from .test_run_endpoint import _headers


def apply(client, h, b):
    r = client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------------------------- pure calculation: deadline planning
def test_deadline_planning_consumes_three_productive_hours_then_shows_shortfall_on_a_later_release():
    received = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
    due = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    picker = [WorkerCapacity(worker_id="w1", rate_per_hour=100, rate_source="personal_activity_rate")]
    plan = schedule_activity(sequence=1, activity="picking", quantity=300, release_at=received, due_at=due, workers=picker)
    assert plan.shortfall_quantity == 0
    assert plan.productive_hours_used == pytest.approx(3.0)
    assert plan.completed_at == due

    later_release = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    plan2 = schedule_activity(sequence=1, activity="picking", quantity=300, release_at=later_release, due_at=due, workers=picker)
    assert plan2.shortfall_quantity == pytest.approx(100.0)
    assert plan2.completed_at is None


# --------------------------------------------------------------------------------------------- pure calculation: personal rates
def test_two_pickers_combine_personal_rates_for_360_units_in_one_hour():
    received = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
    due = datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)
    workers = [WorkerCapacity(worker_id="w1", rate_per_hour=80, rate_source="personal_activity_rate"),
               WorkerCapacity(worker_id="w2", rate_per_hour=280, rate_source="personal_activity_rate")]
    plan = schedule_activity(sequence=1, activity="picking", quantity=360, release_at=received, due_at=due, workers=workers)
    assert plan.shortfall_quantity == 0
    assert plan.completed_at == due


def test_activity_rate_precedence_never_double_applies_productivity_index():
    rate, source = resolve_activity_rate(personal_rate=280, role_rate=None, day_rate=None, standard_rate_per_hour=50, productivity_index=1.5)
    assert rate == 280 and source == "personal_activity_rate"  # productivity_index ignored once a personal rate exists
    rate2, source2 = resolve_activity_rate(personal_rate=None, role_rate=None, day_rate=None, standard_rate_per_hour=50, productivity_index=1.5)
    assert rate2 == 75 and source2 == "activity_standard_adjusted_by_productivity_index"
    with pytest.raises(ValueError):
        resolve_activity_rate(personal_rate=None, role_rate=None, day_rate=None, standard_rate_per_hour=None, productivity_index=None)


# --------------------------------------------------------------------------------------------- pure calculation: process flow precedence
def test_pack_follows_its_own_orders_pick_plus_lag_and_unrelated_orders_are_independent():
    order_a_received = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
    due = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
    fast_workers = {"picking": [WorkerCapacity("w1", 1000, "x")], "packing": [WorkerCapacity("w2", 1000, "x")]}
    steps = [(1, "picking", 0), (2, "packing", 0)]
    plans_a = plan_order_steps(order_received=order_a_received, despatch_due=due, quantity=100, steps=steps, workers_by_activity=fast_workers)
    pick_a, pack_a = plans_a
    assert pack_a.release_at == pick_a.completed_at  # zero lag: pack starts exactly when pick finishes, for the SAME order

    # An unrelated order, already further along, packs independently — its own cursor, not pick_a's.
    order_b_received = datetime(2026, 10, 12, 8, 0, tzinfo=timezone.utc)
    plans_b = plan_order_steps(order_received=order_b_received, despatch_due=due, quantity=50, steps=steps, workers_by_activity=fast_workers)
    pick_b, pack_b = plans_b
    assert pack_b.release_at == pick_b.completed_at
    assert pack_b.release_at != pack_a.release_at  # independent cursors, no shared global sequencing


def test_lag_minutes_delays_the_next_step_after_completion():
    received = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
    due = datetime(2026, 10, 12, 18, 0, tzinfo=timezone.utc)
    workers = {"picking": [WorkerCapacity("w1", 100, "x")], "packing": [WorkerCapacity("w2", 100, "x")]}
    plans = plan_order_steps(order_received=received, despatch_due=due, quantity=100, steps=[(1, "picking", 0), (2, "packing", 15)], workers_by_activity=workers)
    pick, pack = plans
    assert pack.release_at == pick.completed_at + timedelta(minutes=15)


# --------------------------------------------------------------------------------------------- pure calculation: unit conversion
def test_lines_convert_to_units_but_units_is_authoritative_when_present():
    conversions = {("picking", "lines", "units"): 3.2}
    assert resolve_order_quantity(units=None, lines=10, activity="picking", conversions=conversions) == pytest.approx(32.0)
    assert resolve_order_quantity(units=32, lines=10, activity="picking", conversions=conversions) == 32  # units wins; lines never added
    with pytest.raises(ValueError, match="no unit conversion"):
        resolve_order_quantity(units=None, lines=10, activity="packing", conversions=conversions)


# --------------------------------------------------------------------------------------------- import: process templates/steps/orders/rates/conversions
def test_process_template_step_order_import_round_trip(client):
    seed(client)
    h = admin()
    pt = csv_text(["site", "process_code", "customer_id"], [[MEL, "outbound_standard", ""]])
    apply(client, h, stage(client, h, "master", pt, entity="process_templates").json())

    bad_step = csv_text(["site", "process_code", "sequence", "activity", "lag_minutes"], [[MEL, "nope", "1", "picking", "0"]])
    assert stage(client, h, "master", bad_step, entity="process_steps").json()["error_rows"] == 1

    steps = csv_text(["site", "process_code", "sequence", "activity", "lag_minutes"],
                     [[MEL, "outbound_standard", "1", "picking", "0"], [MEL, "outbound_standard", "2", "packing", "0"]])
    apply(client, h, stage(client, h, "master", steps, entity="process_steps").json())
    with client.session_local() as s:
        tmpl = s.scalar(select(ProcessTemplate).where(ProcessTemplate.tenant_id == "ten_test", ProcessTemplate.site_id == MEL, ProcessTemplate.process_code == "outbound_standard"))
        rows = list(s.scalars(select(ProcessStep).where(ProcessStep.process_template_id == tmpl.id).order_by(ProcessStep.sequence)))
        assert [r.activity for r in rows] == ["picking", "packing"]

    bad_order = csv_text(["site", "order_id", "order_received", "despatch_due", "units", "process_code"],
                         [[MEL, "SO-1", "2026-10-12 12:00", "2026-10-12 09:00", "100", "outbound_standard"]])
    assert stage(client, h, "master", bad_order, entity="orders").json()["error_rows"] == 1  # due before received

    missing_qty = csv_text(["site", "order_id", "order_received", "despatch_due", "process_code"],
                           [[MEL, "SO-1", "2026-10-12 09:00", "2026-10-12 13:00", "outbound_standard"]])
    assert stage(client, h, "master", missing_qty, entity="orders").json()["error_rows"] == 1  # no units/lines

    good_order = csv_text(["site", "order_id", "order_received", "despatch_due", "units", "process_code"],
                          [[MEL, "SO-1", "2026-10-12 09:00", "2026-10-12 13:00", "100", "outbound_standard"]])
    done = apply(client, h, stage(client, h, "master", good_order, entity="orders").json())
    assert done["summary"]["applied"] == {"created": 1, "updated": 0}
    with client.session_local() as s:
        o = s.scalar(select(Order).where(Order.tenant_id == "ten_test", Order.site_id == MEL, Order.order_ref == "SO-1"))
        assert o.units == 100 and o.process_template_id == tmpl.id


def test_worker_activity_rate_and_unit_conversion_import(client):
    seed(client)
    h = admin()
    staff = csv_text(["Employee ID", "Full Name", "Location", "Type"], [["E1", "Ann Lee", MEL, "permanent"]])
    apply(client, h, stage(client, h, "master", staff, entity="workers").json())

    rates = csv_text(["worker_ref", "activity", "rate_per_hour"], [["E1", "picking", "280"]])
    done = apply(client, h, stage(client, h, "master", rates, entity="worker_activity_rates").json())
    assert done["summary"]["applied"]["created"] == 1
    with client.session_local() as s:
        from app.models.canonical import Worker
        wid = s.scalar(select(Worker.worker_id).where(Worker.tenant_id == "ten_test", Worker.source_ref == "E1"))
        r = s.scalar(select(WorkerActivityRate).where(WorkerActivityRate.tenant_id == "ten_test", WorkerActivityRate.worker_id == wid))
        assert r.rate_per_hour == 280

    same_unit = csv_text(["activity", "from_unit", "to_unit", "factor"], [["", "lines", "lines", "1.0"]])
    assert stage(client, h, "master", same_unit, entity="unit_conversions").json()["error_rows"] == 1

    conv = csv_text(["activity", "from_unit", "to_unit", "factor"], [["", "lines", "units", "3.2"]])
    done2 = apply(client, h, stage(client, h, "master", conv, entity="unit_conversions").json())
    assert done2["summary"]["applied"]["created"] == 1
    with client.session_local() as s:
        c = s.scalar(select(UnitConversion).where(UnitConversion.tenant_id == "ten_test", UnitConversion.from_unit == "lines"))
        assert c.factor == 3.2 and c.activity is None


# --------------------------------------------------------------------------------------------- end-to-end: order_fulfillment run
def test_order_fulfillment_run_reports_deadline_shortfall_end_to_end(client):
    seed(client)
    h = admin()
    staff = csv_text(["Employee ID", "Full Name", "Location", "Type"], [["E1", "Ann Lee", MEL, "permanent"]])
    apply(client, h, stage(client, h, "master", staff, entity="workers").json())
    rates = csv_text(["worker_ref", "activity", "rate_per_hour"], [["E1", "picking", "100"]])
    apply(client, h, stage(client, h, "master", rates, entity="worker_activity_rates").json())
    pt = csv_text(["site", "process_code", "customer_id"], [[MEL, "outbound_standard", ""]])
    apply(client, h, stage(client, h, "master", pt, entity="process_templates").json())
    steps = csv_text(["site", "process_code", "sequence", "activity"], [[MEL, "outbound_standard", "1", "picking"]])
    apply(client, h, stage(client, h, "master", steps, entity="process_steps").json())
    order = csv_text(["site", "order_id", "order_received", "despatch_due", "units", "process_code"],
                     [[MEL, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", "300", "outbound_standard"]])
    apply(client, h, stage(client, h, "master", order, entity="orders").json())

    body = {
        "request_id": str(uuid.uuid4()), "scope": {"tenant_id": "ten_test", "site_ids": [MEL], "customer_ids": ["cust_A"]},
        "planning_window": {"start": "2026-10-12T00:00:00Z", "end": "2026-10-13T00:00:00Z", "timezone": "Australia/Melbourne", "bucket_minutes": 60},
    }
    response = client.post("/v1/optimisations/order_fulfillment", json=body, headers=_headers())
    assert response.status_code == 202, response.text
    run = response.json()
    assert run["status"] == "completed"
    fetched = client.get(f"/v1/runs/{run['run_id']}", headers=context_header()).json()
    kpis = fetched["result"]["kpis"]
    assert kpis["total_shortfall_quantity"] == 0
    assert fetched["result"]["orders"][0]["on_time"] is True
