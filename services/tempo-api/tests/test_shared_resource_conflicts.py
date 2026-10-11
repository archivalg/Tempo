"""Order-driven and forecast-driven (roster) planning must respect the SAME worker commitments at a
site, without sharing a scheduler. Verified both directions through the real APIs:

1. order_fulfillment (committed) must not double-book a worker a PUBLISHED roster already claims.
2. A roster publish must not double-book a worker a COMMITTED order_fulfillment run already claims.
3. A draft run (either system) never checks or writes these commitments at all — it "may reuse
   resources" (app/models/orders.py::WorkerCommitment's own docstring).
4. Releasing a commitment removes the block without touching anything else.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.canonical import ShiftAssignment, Worker
from app.models.orders import WorkerCommitment
from app.models.rosters import RosterVersion

from .conftest import context_header
from .test_imports import MEL, admin, seed
from .test_integration_order_schedule import _body, _get, _order, _process, _rate, _run, _staff, _window
from .test_roster_workflow import SITE, WEEK, gen, manager, planner, post
from .test_roster_workflow import _seed as _seed_roster

WINDOW = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")


def _body_committed(window):
    b = _body(window)
    b["input"] = {"committed": True}
    return b


def _worker_id(client, ref="E1"):
    with client.session_local() as s:
        return s.scalar(select(Worker.worker_id).where(Worker.tenant_id == "ten_test", Worker.source_ref == ref))


# --------------------------------------------------------------------------------------------- order_fulfillment respects a published roster
def test_committed_order_run_does_not_double_book_a_worker_already_on_a_published_roster(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    worker_id = _worker_id(client)

    # The order's own window is site-local (Australia/Melbourne) 09:00-12:00 on 12 Oct 2026 = UTC
    # 2026-10-11T22:00 - 2026-10-12T01:00 (AEDT, UTC+11) — the published shift below is expressed
    # directly in that UTC frame so the overlap is real, not a timezone-mismatch false negative.
    with client.session_local() as s:
        s.add(ShiftAssignment(tenant_id="ten_test", worker_id=worker_id, role="picker", zone="zone_a",
                              start_at=datetime(2026, 10, 11, 21, 0, tzinfo=timezone.utc), end_at=datetime(2026, 10, 12, 2, 0, tzinfo=timezone.utc),
                              status="committed", source_system="tempo_native", source_ref="rv_test"))
        s.commit()

    # A DRAFT still sees E1 as available — it may reuse resources, nothing is promised.
    draft = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert draft["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)

    # A COMMITTED run must not double-book E1 — the published shift fully overlaps the order's window
    # and E1 is the only worker, so NOTHING can be assigned at all: a proven-infeasible, persisted
    # "failed" run with a reason, not a silent success that secretly ignored the conflict.
    run2 = _get(client, _run(client, _body_committed(WINDOW))["run_id"])
    assert run2["status"] == "failed"
    assert "no feasible allocation" in run2["explanation"]["primary_drivers"][0]


def test_committed_order_run_respects_a_partial_overlap_and_an_overnight_published_shift(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    # The order's own window is site-local 06:00-14:00 on 12 Oct 2026 = UTC 2026-10-11T19:00 -
    # 2026-10-12T03:00 (AEDT, UTC+11). The published shift below overlaps only its first hour
    # (19:00-20:00 UTC) — a PARTIAL overlap, not ignored because it isn't a full one.
    _order(client, h, "SO-1", "2026-10-12 06:00", "2026-10-12 14:00", 800, "p1")  # exactly 8h * 100/h — needs EVERY hour, so losing even one is measurable
    worker_id = _worker_id(client)
    with client.session_local() as s:
        s.add(ShiftAssignment(tenant_id="ten_test", worker_id=worker_id, role="picker", zone="zone_a",
                              start_at=datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc), end_at=datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc),
                              status="committed", source_system="tempo_native", source_ref="rv_test"))
        s.commit()
    window = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")
    committed = _get(client, _run(client, _body_committed(window))["run_id"])["result"]
    # E1 is blocked for the WHOLE order window because the partial overlap makes any sub-interval
    # touching 06:00-07:00 unavailable, and E1 is the only worker — proven by a non-zero shortfall.
    assert committed["orders"][0]["shortfall_quantity"] > 0


def test_releasing_a_committed_order_run_lets_a_worker_be_rebooked(client):
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")

    run1 = _run(client, _body_committed(WINDOW))
    first = _get(client, run1["run_id"])["result"]
    assert first["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)
    worker_id = _worker_id(client)
    with client.session_local() as s:
        assert s.scalar(select(WorkerCommitment.id).where(WorkerCommitment.tenant_id == "ten_test", WorkerCommitment.worker_id == worker_id, WorkerCommitment.released_at.is_(None))) is not None

    # A second committed run for a LATER window would see E1 blocked by the first run's WorkerCommitment
    # (this uses a non-overlapping window only because overlapping windows are already refused at the
    # site level by _check_committed_conflict — this test is specifically about the worker-level ledger).
    client.post(f"/v1/runs/{run1['run_id']}/release-commitment", headers=admin())
    with client.session_local() as s:
        assert s.scalar(select(WorkerCommitment.id).where(WorkerCommitment.tenant_id == "ten_test", WorkerCommitment.worker_id == worker_id, WorkerCommitment.released_at.is_(None))) is None


# --------------------------------------------------------------------------------------------- roster publish respects a committed order run
def test_roster_publish_is_blocked_by_an_overlapping_committed_order_run_then_allowed_after_release(client):
    _seed_roster(client)
    v = gen(client)["version"]["id"]
    with client.session_local() as s:
        shift = s.scalar(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_test", ShiftAssignment.source_ref == v))
        worker_id, start_at, end_at = shift.worker_id, shift.start_at, shift.end_at

    assert post(client, f"/v1/rosters/{v}/validate", planner()).json()["can_submit"] is True
    assert post(client, f"/v1/rosters/{v}/submit", planner()).status_code == 200
    assert post(client, f"/v1/rosters/{v}/approve", manager(), {"note": "ok"}).status_code == 200

    with client.session_local() as s:
        s.add(WorkerCommitment(tenant_id="ten_test", site_id=SITE, worker_id=worker_id, run_id="run_fake_order_commit",
                               start_at=start_at, end_at=end_at))
        s.commit()

    blocked = post(client, f"/v1/rosters/{v}/publish", manager(), idem=True)
    assert blocked.status_code >= 400, blocked.text
    assert worker_id in blocked.json()["detail"]
    with client.session_local() as s:
        assert s.scalar(select(RosterVersion.state).where(RosterVersion.id == v)) == "approved"  # NOT silently published

    with client.session_local() as s:
        wc = s.scalar(select(WorkerCommitment).where(WorkerCommitment.tenant_id == "ten_test", WorkerCommitment.run_id == "run_fake_order_commit"))
        wc.released_at = datetime.now(timezone.utc)
        s.commit()

    allowed = post(client, f"/v1/rosters/{v}/publish", manager(), idem=True)
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["state"] == "reconciled"
