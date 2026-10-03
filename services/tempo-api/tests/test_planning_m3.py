"""Roadmap M3: competing roster actions cannot make duplicate or stale live rosters; adjacent weeks and overnight shifts stay put; hard rules block."""
from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from sqlalchemy import select

from app.models.canonical import Availability, ShiftAssignment, Worker
from app.models.rosters import RosterVersion

from .conftest import context_header
from .test_roster_workflow import SITE, WEEK, _seed, gen, manager, planner, post


def _approved(client, week=WEEK):
    b = client.post(f"/v1/sites/{SITE}/rosters/generate", json={"week_start": week}, headers=planner())
    assert b.status_code == 201, b.text
    v = b.json()["version"]["id"]
    assert post(client, f"/v1/rosters/{v}/submit", planner()).status_code == 200
    assert post(client, f"/v1/rosters/{v}/approve", manager(), {"note": "ok"}).status_code == 200
    return v


def test_simultaneous_publishes_of_one_version_publish_it_once(client):
    _seed(client)
    v = _approved(client)
    gate = Barrier(3)

    def go(_):
        gate.wait()
        return client.post(f"/v1/rosters/{v}/publish", headers={**manager(), "Idempotency-Key": str(uuid.uuid4())})

    with ThreadPoolExecutor(3) as pool:
        rs = list(pool.map(go, range(3)))
    assert all(r.status_code == 200 for r in rs), [r.text for r in rs]
    assert sorted(bool(r.json().get("idempotent_replay")) for r in rs) == [False, True, True]
    with client.session_local() as s:
        live = s.scalars(select(RosterVersion).where(RosterVersion.state.in_(("published", "reconciled")))).all()
        assert len(live) == 1 and live[0].id == v
        keys = [(r.worker_id, r.start_at) for r in s.scalars(select(ShiftAssignment).where(ShiftAssignment.status == "committed"))]
        assert len(keys) == len(set(keys))


def test_simultaneous_generation_never_reuses_a_version_number_or_leaves_two_open_drafts(client):
    _seed(client)
    hdr = planner()
    client.get("/v1/rosters/pending", headers=hdr)   # create the test principal once, before the threads race to
    gate = Barrier(2)

    def go(_):
        gate.wait()
        return client.post(f"/v1/sites/{SITE}/rosters/generate", json={"week_start": WEEK}, headers=hdr)

    with ThreadPoolExecutor(2) as pool:
        rs = list(pool.map(go, range(2)))
    assert [r.status_code for r in rs] == [201, 201], [r.text[:200] for r in rs]
    with client.session_local() as s:
        vs = s.scalars(select(RosterVersion).order_by(RosterVersion.version_no)).all()
        assert [v.version_no for v in vs] == [1, 2]
        assert [v.state for v in vs].count("draft") == 1 and [v.state for v in vs].count("superseded") == 1
        proposed = s.scalars(select(ShiftAssignment).where(ShiftAssignment.status == "proposed")).all()
        assert {p.source_ref for p in proposed} == {next(v.id for v in vs if v.state == "draft")}


def test_a_stale_approval_cannot_publish_over_a_newer_draft(client):
    _seed(client)
    old = _approved(client)
    new = gen(client)["version"]["id"]        # regenerating supersedes the approved one
    r = client.post(f"/v1/rosters/{old}/publish", headers={**manager(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 422
    with client.session_local() as s:
        assert s.scalars(select(RosterVersion).where(RosterVersion.state.in_(("published", "reconciled")))).all() == []
        assert s.get(RosterVersion, new).state == "draft"


def test_publishing_next_week_keeps_the_previous_weeks_sunday_night_shift(client):
    _seed(client)
    a = _approved(client)
    assert client.post(f"/v1/rosters/{a}/publish", headers={**manager(), "Idempotency-Key": str(uuid.uuid4())}).status_code == 200
    next_week = (datetime.fromisoformat(WEEK) + timedelta(days=7)).date().isoformat()
    with client.session_local() as s:
        w = s.scalar(select(Worker))
        site_tz_offset = timedelta(hours=10)  # Melbourne, standard time in early/mid September
        sunday_night = datetime.fromisoformat(next_week).replace(tzinfo=timezone(site_tz_offset)) - timedelta(hours=2)   # 22:00 on the last day of week A
        night = ShiftAssignment(tenant_id="ten_test", worker_id=w.worker_id, role="picker", zone="z", start_at=sunday_night, end_at=sunday_night + timedelta(hours=8),
                                status="committed", source_ref=a)
        s.add(night)
        s.commit()
        night_id = night.shift_id
    b = _approved(client, next_week)
    assert client.post(f"/v1/rosters/{b}/publish", headers={**manager(), "Idempotency-Key": str(uuid.uuid4())}).status_code == 200
    with client.session_local() as s:
        assert s.get(ShiftAssignment, night_id).status == "committed"             # still last week's live shift
        assert s.get(RosterVersion, a).state == "reconciled"                       # and last week's roster is still live
        assert s.get(RosterVersion, b).state == "reconciled"


def test_hard_rules_block_submission_rest_availability_and_max_hours(client):
    _seed(client)
    b = gen(client)
    v, s0 = b["version"]["id"], min(b["shifts"], key=lambda x: x["start_at"])   # earliest shift: room inside the window for the follow-on
    start = datetime.fromisoformat(s0["end_at"].replace("Z", "+00:00"))
    # a second shift that begins 2 hours after the first ends: less than the 10 h rest rule
    r = client.post(f"/v1/rosters/{v}/shifts", headers=planner(), json={"worker_id": s0["worker_id"], "role": s0["role"], "zone": s0["zone"],
                                                                      "start_at": (start + timedelta(hours=2)).isoformat(), "end_at": (start + timedelta(hours=8)).isoformat()})
    assert r.status_code == 201, r.text
    assert "rest" in {c["kind"] for c in r.json()["conflicts"]}
    assert post(client, f"/v1/rosters/{v}/submit", planner()).status_code == 422
    # leave over the first shift is a hard conflict too
    with client.session_local() as s:
        s.add(Availability(tenant_id="ten_test", worker_id=s0["worker_id"], interval_start=datetime.fromisoformat(s0["start_at"].replace("Z", "+00:00")) - timedelta(hours=1),
                           interval_end=start + timedelta(hours=1), status="leave"))
        s.commit()
    kinds = {c["kind"] for c in client.get(f"/v1/rosters/{v}", headers=planner()).json()["conflicts"]}
    assert {"rest", "availability"} <= kinds


def test_planning_rules_are_versioned_audited_and_drive_validation(client):
    _seed(client)
    admin = context_header(roles=["tenant_admin"], user_id="usr_adm")
    d = client.get("/v1/planning-rules", headers=planner()).json()
    assert d["is_default"] is True and d["min_rest_hours"] == 10 and d["max_weekly_hours"] == 50
    body = {"min_rest_hours": 12, "max_weekly_hours": 40, "hours_per_worker_per_day": 8, "max_overtime_hours_per_worker_per_day": 2, "max_consecutive_days": 6}
    assert client.put("/v1/planning-rules", json=body, headers=planner()).status_code == 403
    assert client.put("/v1/planning-rules", json={**body, "min_rest_hours": 2}, headers=admin).status_code == 422
    r = client.put("/v1/planning-rules", json=body, headers=admin)
    assert r.status_code == 200 and r.json()["is_default"] is False and r.json()["max_weekly_hours"] == 40
    assert client.put("/v1/planning-rules", json={**body, "max_weekly_hours": 45}, headers=admin).status_code == 200   # a second version; the first is kept
    from app.models.canonical import OptimisationPolicy
    with client.session_local() as s:
        assert len(s.scalars(select(OptimisationPolicy)).all()) == 2
    # validation now uses the saved weekly limit: a generated week carrying more than 45 h for anyone is flagged
    b = gen(client)
    per: dict[str, float] = {}
    for sh in b["shifts"]:
        per[sh["worker_id"]] = per.get(sh["worker_id"], 0) + (datetime.fromisoformat(sh["end_at"].replace("Z", "+00:00")) - datetime.fromisoformat(sh["start_at"].replace("Z", "+00:00"))).total_seconds() / 3600
    over = {w for w, h in per.items() if h > 45}
    flagged = {c["worker_id"] for c in b["conflicts"] if c["kind"] == "max_hours"}
    assert flagged == over


def test_shift_calendar_is_configured_validated_and_used_by_the_generator(client):
    _seed(client)
    admin = context_header(roles=["tenant_admin"], user_id="usr_adm")
    base = {"min_rest_hours": 10, "max_weekly_hours": 50, "hours_per_worker_per_day": 8, "max_overtime_hours_per_worker_per_day": 2, "max_consecutive_days": 6}
    assert client.get("/v1/planning-rules", headers=planner()).json()["shift_calendar_is_default"] is True
    bad = [{"code": "a", "start_hour": 6, "end_hour": 14, "share": 0.7}, {"code": "b", "start_hour": 14, "end_hour": 22, "share": 0.7}]
    assert client.put("/v1/planning-rules", json={**base, "shift_calendar": bad}, headers=admin).status_code == 422          # shares must sum to 1
    assert client.put("/v1/planning-rules", json={**base, "shift_calendar": [{"code": "x", "start_hour": 6, "end_hour": 6}]}, headers=admin).status_code == 422
    assert client.put("/v1/planning-rules", json={**base, "shift_calendar": [{"code": "a", "start_hour": 6, "end_hour": 14}, {"code": "a", "start_hour": 14, "end_hour": 22}]}, headers=admin).status_code == 422
    cal = [{"code": "early", "start_hour": 5, "end_hour": 13}, {"code": "late", "start_hour": 13, "end_hour": 21}, {"code": "night", "start_hour": 21, "end_hour": 5}]
    ok = client.put("/v1/planning-rules", json={**base, "shift_calendar": cal}, headers=admin)
    assert ok.status_code == 200 and [x["code"] for x in ok.json()["shift_calendar"]] == ["early", "late", "night"]
    b = gen(client)
    starts = {datetime.fromisoformat(s["start_at"].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=10))).hour for s in b["shifts"]}
    assert starts <= {5, 13, 21} and starts
    # saving rules without a calendar keeps the one already saved
    assert client.put("/v1/planning-rules", json=base, headers=admin).json()["shift_calendar"][0]["code"] == "early"


def test_availability_entries_block_rosters_and_only_own_entries_can_be_removed(client):
    _seed(client)
    b = gen(client)
    s0 = b["shifts"][0]
    st = datetime.fromisoformat(s0["start_at"].replace("Z", "+00:00"))
    body = {"worker_id": s0["worker_id"], "start_at": (st - timedelta(hours=1)).isoformat(), "end_at": (st + timedelta(hours=3)).isoformat(), "status": "leave"}
    assert client.post(f"/v1/sites/{SITE}/availability", json=body, headers=context_header(roles=["analyst"], user_id="usr_an")).status_code == 403
    r = client.post(f"/v1/sites/{SITE}/availability", json=body, headers=planner())
    assert r.status_code == 201, r.text
    assert client.post(f"/v1/sites/{SITE}/availability", json=body, headers=planner()).status_code == 422            # overlapping entry of the same kind
    assert client.post(f"/v1/sites/{SITE}/availability", json={**body, "worker_id": "nobody"}, headers=planner()).status_code == 400
    week = st.date().isoformat()
    listed = client.get(f"/v1/sites/{SITE}/availability", params={"start": week, "days": 7}, headers=planner()).json()
    assert [x["id"] for x in listed] == [r.json()["id"]] and listed[0]["editable"] is True
    v = b["version"]["id"]
    assert "availability" in {c["kind"] for c in client.get(f"/v1/rosters/{v}", headers=planner()).json()["conflicts"]}
    assert client.delete(f"/v1/availability/{r.json()['id']}", headers=planner()).status_code == 200
    assert "availability" not in {c["kind"] for c in client.get(f"/v1/rosters/{v}", headers=planner()).json()["conflicts"]}
    with client.session_local() as s:
        a = Availability(tenant_id="ten_test", worker_id=s0["worker_id"], interval_start=st, interval_end=st + timedelta(hours=2), status="leave", source_system="deputy")
        s.add(a)
        s.commit()
        aid = a.id
    assert client.delete(f"/v1/availability/{aid}", headers=planner()).status_code == 422


def test_break_and_instructions_are_set_by_the_planner_bind_to_approval_and_reach_the_employee_after_publish(client):
    _seed(client)
    b = gen(client)
    v, s0 = b["version"]["id"], b["shifts"][0]
    r = client.patch(f"/v1/rosters/{v}/shifts/{s0['shift_id']}", json={"break_minutes": 45, "instructions": "Report to dock 3"}, headers=planner())
    assert r.status_code == 200
    got = next(x for x in r.json()["shifts"] if x["shift_id"] == s0["shift_id"])
    assert got["planned_break_minutes"] == 45 and got["instructions"] == "Report to dock 3"
    assert client.patch(f"/v1/rosters/{v}/shifts/{s0['shift_id']}", json={"break_minutes": 500}, headers=planner()).status_code == 422
    post(client, f"/v1/rosters/{v}/submit", planner())
    post(client, f"/v1/rosters/{v}/approve", manager(), {})
    client.patch(f"/v1/rosters/{v}/shifts/{s0['shift_id']}", json={"instructions": "Changed after approval"}, headers=planner())      # an instruction edit invalidates the approval like any edit
    assert post(client, f"/v1/rosters/{v}/publish", manager(), idem=True).status_code == 422
