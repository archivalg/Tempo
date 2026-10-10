"""Arch acceptance correction: committing a roster is a PLAN, not a confirmation that work physically
happened. `Order.committed_units` (what a committed run has planned) and `Order.fulfilled_units`
(what is confirmed actually done) are deliberately separate fields with separate writers — see
app/models/orders.py and app/api/v1/orders.py. Verified through the real run-creation and
order-completion APIs.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models.orders import Order

from .test_imports import MEL, admin, seed
from .test_integration_order_schedule import _body, _get, _order, _process, _rate, _run, _staff, _window
from .test_run_endpoint import _headers

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


# --------------------------------------------------------------------------------------------- outstanding vs available for planning
def test_get_order_distinguishes_outstanding_from_available_for_planning(client):
    """The two numbers are the SAME only when nothing has been committed yet; a committed-but-not-yet-
    confirmed plan is the common case where they diverge."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 1000, "p1")
    order = _order_row(client)

    before = client.get(f"/v1/orders/{order.id}", headers=h).json()
    assert before["outstanding_quantity"] == before["available_for_planning"] == 1000  # nothing committed or done yet

    _get(client, _run(client, _body_committed(WINDOW))["run_id"])  # commits 300
    mid = client.get(f"/v1/orders/{order.id}", headers=h).json()
    assert mid["outstanding_quantity"] == 1000       # nothing is ACTUALLY done yet — all 1000 remain outstanding in the real world
    assert mid["available_for_planning"] == 700      # but only 700 is safe to schedule again — 300 is already promised elsewhere

    _complete(client, h, order.id, 300)  # now actually confirmed done
    after = client.get(f"/v1/orders/{order.id}", headers=h).json()
    assert after["outstanding_quantity"] == 700       # real outstanding work has genuinely shrunk
    assert after["available_for_planning"] == 700     # and now the two agree again, since committed == fulfilled


# --------------------------------------------------------------------------------------------- partial actual completion
def test_partial_actual_completion_is_additive_and_bounded(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    order = _order_row(client)

    _complete(client, h, order.id, 100)
    _complete(client, h, order.id, 100)
    assert _order_row(client).fulfilled_units == pytest.approx(200, abs=0.01)
    assert _order_row(client).status == "open"

    over = client.post(f"/v1/orders/{order.id}/complete", json={"quantity": 500}, headers=h)  # far more than remains
    assert over.status_code == 200
    assert over.json()["fulfilled_units"] == pytest.approx(300, abs=0.01)  # clamped to the order's own total, never exceeds it
    assert over.json()["status"] == "completed"


# --------------------------------------------------------------------------------------------- cancellation / release
def test_cancelling_a_committed_run_releases_its_commitment_for_rescheduling(client):
    """Released reservations must make unfinished work available again."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 1000, "p1")

    run = _run(client, _body_committed(WINDOW))
    assert _order_row(client).committed_units == pytest.approx(300, abs=0.5)

    rel = client.post(f"/v1/runs/{run['run_id']}/release-commitment", headers=h)
    assert rel.status_code == 200, rel.text
    assert rel.json()["released"][0]["quantity"] == pytest.approx(300, abs=0.5)
    assert _order_row(client).committed_units == 0.0  # fully released
    assert _order_row(client).fulfilled_units == 0.0  # actual completion is untouched by a planning action

    # A new committed run for the SAME window is now allowed (no conflict — the prior one was released)
    # and sees the FULL quantity available again, not the 300 still (incorrectly) reserved.
    again = _get(client, _run(client, _body_committed(WINDOW))["run_id"])["result"]
    assert again["orders"][0]["quantity"] == pytest.approx(1000, abs=0.5)


def test_releasing_an_already_released_commitment_is_a_harmless_no_op(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    run = _run(client, _body_committed(WINDOW))
    client.post(f"/v1/runs/{run['run_id']}/release-commitment", headers=h)
    second = client.post(f"/v1/runs/{run['run_id']}/release-commitment", headers=h)
    assert second.status_code == 200 and second.json()["released"] == []  # nothing left to release — not an error


def test_releasing_one_run_never_touches_a_different_runs_commitment(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-A", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    _order(client, h, "SO-B", "2026-10-14 09:00", "2026-10-14 12:00", 300, "p1")  # a different, non-overlapping window — two SEPARATE committed runs, not one
    window2 = _window("2026-10-13T12:00:00Z", "2026-10-16T12:00:00Z")
    run_a = _run(client, _body_committed(WINDOW))
    run_b = _run(client, _body_committed(window2))
    assert _order_row(client, "SO-A").committed_units == pytest.approx(300, abs=0.5)
    assert _order_row(client, "SO-B").committed_units == pytest.approx(300, abs=0.5)

    client.post(f"/v1/runs/{run_a['run_id']}/release-commitment", headers=h)
    assert _order_row(client, "SO-A").committed_units == 0.0           # run_a's commitment released...
    assert _order_row(client, "SO-B").committed_units == pytest.approx(300, abs=0.5)  # ...run_b's is completely untouched


# --------------------------------------------------------------------------------------------- repeated requests / overlap
def test_repeated_commit_request_with_same_idempotency_key_does_not_duplicate(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    body = _body_committed(WINDOW)
    body["request_id"] = str(uuid.uuid4())
    fixed_headers = _headers()  # ONE idempotency key, reused for both calls

    r1 = client.post("/v1/optimisations/order_fulfillment", json=body, headers=fixed_headers)
    assert r1.status_code == 202
    r2 = client.post("/v1/optimisations/order_fulfillment", json=body, headers=fixed_headers)  # the exact same request, retried
    assert r2.status_code == 202
    assert r1.json()["run_id"] == r2.json()["run_id"]  # the SAME run is returned, not a second one
    assert _order_row(client).committed_units == pytest.approx(300, abs=0.5)  # committed exactly once, not twice


def test_overlapping_commitment_rejected_then_allowed_after_release(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    run = _run(client, _body_committed(WINDOW))

    body2 = _body_committed(WINDOW)  # same site, overlapping window
    body2["request_id"] = str(uuid.uuid4())
    conflict = client.post("/v1/optimisations/order_fulfillment", json=body2, headers=_headers())
    assert conflict.status_code == 422 and "overlapping window" in conflict.json()["detail"]

    client.post(f"/v1/runs/{run['run_id']}/release-commitment", headers=h)
    body3 = _body_committed(WINDOW)
    body3["request_id"] = str(uuid.uuid4())
    now_allowed = client.post("/v1/optimisations/order_fulfillment", json=body3, headers=_headers())
    assert now_allowed.status_code == 202, now_allowed.text  # the earlier commitment no longer blocks — it was released


def test_actual_completion_unchanged_by_commit_release_or_replan(client):
    """The whole point: planning actions (commit, release, re-commit) must never move
    `fulfilled_units` — only an explicit completion confirmation ever does."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    order = _order_row(client)
    _complete(client, h, order.id, 150)
    assert _order_row(client).fulfilled_units == pytest.approx(150, abs=0.01)

    run = _run(client, _body_committed(WINDOW))
    assert _order_row(client).fulfilled_units == pytest.approx(150, abs=0.01)  # a commit didn't move it
    client.post(f"/v1/runs/{run['run_id']}/release-commitment", headers=h)
    assert _order_row(client).fulfilled_units == pytest.approx(150, abs=0.01)  # neither did a release
    _run(client, _body_committed(WINDOW))
    assert _order_row(client).fulfilled_units == pytest.approx(150, abs=0.01)  # nor a re-commit
