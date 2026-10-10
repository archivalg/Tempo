"""Arch acceptance correction: committing a roster is a PLAN, not a confirmation that work physically
happened. `Order.committed_units` (what a committed run has planned) and `Order.fulfilled_units`
(what is confirmed actually done) are deliberately separate fields with separate writers — see
app/models/orders.py and app/api/v1/orders.py. Verified through the real run-creation and
order-completion APIs.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models.orders import Order

from .test_imports import MEL, admin, seed
from .test_integration_order_schedule import _body, _get, _order, _process, _rate, _run, _staff, _window

WINDOW = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")


def _body_committed(window):
    b = _body(window)
    b["input"] = {"committed": True}
    return b


def _order_row(client, order_ref="SO-1"):
    with client.session_local() as s:
        return s.scalar(select(Order).where(Order.tenant_id == "ten_test", Order.site_id == MEL, Order.order_ref == order_ref))


def _complete(client, h, order_id, quantity):
    r = client.post(f"/v1/orders/{order_id}/complete", json={"quantity": quantity}, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_committed_run_updates_committed_units_never_fulfilled_units(client):
    """A committed run, even one that fully schedules an order, only ever advances the PLANNED
    allocation — it must never be mistaken for a confirmation that the work physically happened."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")  # fully achievable in one committed run
    result = _get(client, _run(client, _body_committed(WINDOW))["run_id"])["result"]
    assert result["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)  # the PLAN fully covers it...

    order = _order_row(client)
    assert order.committed_units == pytest.approx(300, abs=0.5)   # ...recorded as a plan...
    assert order.fulfilled_units == 0.0                            # ...but NOT as actual completion
    assert order.status == "open"                                  # status only changes on confirmed completion, never on commit


def test_draft_and_committed_plans_both_leave_fulfilled_units_unchanged(client):
    """Neither a draft NOR a committed plan ever marks actual work fulfilled — only an explicit
    completion confirmation does. This holds across every scheduling outcome, not just a successful
    one."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")

    _get(client, _run(client, _body(WINDOW))["run_id"])              # scheduled (draft)
    assert _order_row(client).fulfilled_units == 0.0
    _get(client, _run(client, _body_committed(WINDOW))["run_id"])     # committed
    assert _order_row(client).fulfilled_units == 0.0
    assert _order_row(client).committed_units == pytest.approx(300, abs=0.5)  # the committed run DID plan it...
    assert _order_row(client).status == "open"                                # ...but that is still not "fulfilled"


def test_explicit_completion_confirms_actual_fulfilment_and_flips_status(client):
    """The ONLY path that advances fulfilled_units: an explicit confirmation through
    POST /v1/orders/{id}/complete."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    order = _order_row(client)

    resp = _complete(client, h, order.id, 120)
    assert resp["fulfilled_units"] == pytest.approx(120, abs=0.01) and resp["status"] == "open"
    assert _order_row(client).committed_units == 0.0  # confirming completion never touches the planned-allocation field either

    resp2 = _complete(client, h, order.id, 180)  # the remaining 180 of 300
    assert resp2["fulfilled_units"] == pytest.approx(300, abs=0.01) and resp2["status"] == "completed"


def test_confirmed_completion_reduces_backlog_without_duplication(client):
    """Priority 1, corrected: a committed run plans 300 of 1000; separately confirming that the SAME
    300 units were actually completed must reduce the order's remaining backlog by 300 ONCE, not by
    600 (300 planned + 300 confirmed, double-counted)."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 1000, "p1")  # 100/h * 3h = 300 achievable in this window

    first = _get(client, _run(client, _body_committed(WINDOW))["run_id"])["result"]
    assert first["orders"][0]["shortfall_quantity"] == pytest.approx(700, abs=0.5)
    order = _order_row(client)
    assert order.committed_units == pytest.approx(300, abs=0.5)

    _complete(client, h, order.id, 300)  # actuals/ops confirm the SAME 300 units that were planned really happened
    assert _order_row(client).fulfilled_units == pytest.approx(300, abs=0.01)

    # A second committed run (a later, non-overlapping window — the first window is already claimed)
    window2 = _window("2026-10-13T12:00:00Z", "2026-10-16T12:00:00Z")
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-15 09:00", 1000, "p1")  # extend the deadline into window2
    second = _get(client, _run(client, _body_committed(window2))["run_id"])["result"]
    assert second["orders"][0]["quantity"] == pytest.approx(700, abs=0.5)  # 1000 - max(300 committed, 300 fulfilled) = 700, NOT 1000-600=400
