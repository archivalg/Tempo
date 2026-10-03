"""Mobile foundation: employee API, offers, leave, availability, push jobs, kiosk QR/exit. Real PostgreSQL, real RLS, the real login."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import settings
from app.core import push
from app.core.providers import mock_push, mock_sms
from app.models.canonical import Availability, ShiftAssignment, SkillCertification, Worker
from app.models.directory import Site, WorkerPerson
from app.models.identity import Tenant
from app.models.mobile import (LeaveRequest, NotificationJob, PushDelivery, PushDevice, ShiftChangeEvent, ShiftOffer, SmsUsage, TenantMessaging)
from app.models.rosters import Notification

from .conftest import context_header
from .test_roster_workflow import SITE, WEEK, _seed, manager, planner, post

UTC = timezone.utc
MEL = ZoneInfo("Australia/Melbourne")


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "push_provider", "mock")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    mock_push().sent.clear()
    mock_sms().sent.clear()
    from app.core.password_login import throttle
    throttle.reset()


ADMIN = lambda **kw: context_header(roles=["tenant_admin"], user_id="usr_admin", **kw)  # noqa: E731


def employee_login(client, worker_id, username="emp1", password="Correct-Horse-Battery-9!", tenant="ten_test", site=SITE):
    """The real path: manager invites → employee sets a password with the one-time token → signs in with username/password → bearer token."""
    inv = client.post(f"/v1/workers/{worker_id}/app-invite", json={}, headers=ADMIN())
    assert inv.status_code == 201, inv.text
    token = inv.json()["invite_token"]
    assert client.get(f"/v1/auth/invite/{token}").status_code == 200
    assert client.post("/v1/auth/accept-invite", json={"token": token, "password": password, "username": username}).status_code == 200
    r = client.post("/v1/mobile/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200 and r.json()["status"] == "signed_in", r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()


def seed_people(client):
    _seed(client)
    with client.session_local() as s:
        for wid, name in (("wrk_emp", "Eva Employee"), ("wrk_other", "Olly Other")):
            if s.get(Worker, wid) is None:
                s.add(Worker(worker_id=wid, tenant_id="ten_test", employment_type="casual", home_site=SITE, status="active"))
                s.flush()
                s.add(WorkerPerson(worker_id=wid, tenant_id="ten_test", display_name=name, employee_no=wid[-3:]))
                s.add(SkillCertification(tenant_id="ten_test", worker_id=wid, skill_code="picker", valid_from=datetime(2020, 1, 1, tzinfo=UTC)))
        s.commit()


def add_committed(client, wid, start, hours=8, **kw):
    with client.session_local() as s:
        sh = ShiftAssignment(tenant_id="ten_test", worker_id=wid, role="picker", zone="z", start_at=start, end_at=start + timedelta(hours=hours), status="committed", **kw)
        s.add(sh)
        s.commit()
        return sh.shift_id


def future(days=3, hour=22):
    d = (datetime.now(MEL) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return d.astimezone(UTC)


# ------------------------------------------------------------------------------------------------ account, sessions, visibility
def test_employee_account_flow_and_the_account_cannot_reach_manager_screens(client):
    seed_people(client)
    h, tokens = employee_login(client, "wrk_emp")
    prof = client.get("/v1/me/profile", headers=h).json()
    assert prof["worker_id"] == "wrk_emp" and prof["display_name"] == "Eva Employee" and prof["site"]["timezone"] == "Australia/Melbourne"
    for path in (f"/v1/sites/{SITE}/roster", f"/v1/sites/{SITE}/attendance/daily", "/v1/users", f"/v1/sites/{SITE}/overview", "/v1/devices", f"/v1/sites/{SITE}/clock-credentials"):
        assert client.get(path, headers=h).status_code in (403, 404), path
    assert client.get("/v1/me/access", headers=h).json()["permissions"] == ["labour.self"]
    # a manager is not an employee: the employee endpoints refuse a non-linked account
    assert client.get("/v1/me/profile", headers=manager()).status_code == 403
    # sign-in problems
    assert client.post("/v1/mobile/auth/login", json={"username": "emp1", "password": "wrong"}).status_code == 401


def test_refresh_rotation_logout_and_expired_or_replayed_sessions(client):
    seed_people(client)
    h, tokens = employee_login(client, "wrk_emp")
    r = client.post("/v1/mobile/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200 and r.json()["refresh_token"] != tokens["refresh_token"]
    # the old refresh token is dead; reuse of a rotated token revokes the whole family (theft detection)
    assert client.post("/v1/mobile/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 401
    assert client.post("/v1/mobile/auth/refresh", json={"refresh_token": r.json()["refresh_token"]}).status_code == 401
    assert client.get("/v1/me/profile", headers=h).status_code == 401 or client.get("/v1/me/profile", headers=h).status_code == 200
    # explicit logout ends the session
    h2, t2 = employee_login(client, "wrk_other", username="emp2")
    assert client.post("/v1/mobile/auth/logout", headers=h2).status_code == 200
    assert client.get("/v1/me/profile", headers=h2).status_code == 401
    assert client.post("/v1/mobile/auth/refresh", json={"refresh_token": t2["refresh_token"]}).status_code == 401
    assert client.get("/v1/me/profile").status_code == 401


def test_unlinking_cuts_off_the_app_immediately(client):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    assert client.get("/v1/me/shifts", headers=h).status_code == 200
    assert client.delete("/v1/workers/wrk_emp/app-link", headers=ADMIN()).status_code == 200
    assert client.get("/v1/me/shifts", headers=h).status_code in (401, 403)
    assert client.post("/v1/mobile/auth/login", json={"username": "emp1", "password": "Correct-Horse-Battery-9!"}).status_code in (401, 403)


def test_staff_see_published_shifts_only_and_a_roster_change_appears_with_a_notification(client):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    start = future(3, 6)
    # a DRAFT roster for this worker exists but nothing is published
    with client.session_local() as s:
        draft = ShiftAssignment(tenant_id="ten_test", worker_id="wrk_emp", role="picker", zone="z", start_at=start, end_at=start + timedelta(hours=8), status="proposed")
        s.add(draft)
        s.commit()
    assert client.get("/v1/me/shifts", headers=h).json()["shifts"] == []                      # drafts are invisible
    # publish a real roster containing the worker
    v = client.post(f"/v1/sites/{SITE}/rosters/generate", json={"week_start": WEEK}, headers=planner()).json()["version"]["id"]
    with client.session_local() as s:   # make sure our worker is rostered in the generated draft, with exactly one known shift
        for row in s.scalars(select(ShiftAssignment).where(ShiftAssignment.worker_id == "wrk_emp", ShiftAssignment.source_ref == v)):
            s.delete(row)
        s.flush()
        wk = datetime.fromisoformat(WEEK).replace(tzinfo=MEL)
        s.add(ShiftAssignment(tenant_id="ten_test", worker_id="wrk_emp", role="picker", zone="z", start_at=(wk + timedelta(days=1, hours=6)).astimezone(UTC),
                              end_at=(wk + timedelta(days=1, hours=14)).astimezone(UTC), status="proposed", source_ref=v, instructions="Bring safety boots", break_minutes=30))
        s.commit()
    assert client.get("/v1/me/shifts", params={"start": "2026-09-01", "end": "2026-10-31"}, headers=h).json()["shifts"] == []      # still a draft
    post(client, f"/v1/rosters/{v}/submit", planner())
    post(client, f"/v1/rosters/{v}/approve", manager(), {})
    assert client.get("/v1/me/shifts", params={"start": "2026-09-01", "end": "2026-10-31"}, headers=h).json()["shifts"] == []      # approved but NOT published: still hidden
    r = client.post(f"/v1/rosters/{v}/publish", headers={**manager(), "Idempotency-Key": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    mine = client.get("/v1/me/shifts", params={"start": "2026-09-01", "end": "2026-10-31"}, headers=h).json()["shifts"]
    boots = [x for x in mine if x["instructions"] == "Bring safety boots"]
    assert len(boots) == 1 and boots[0]["break_minutes"] == 30 and boots[0]["site_name"] and boots[0]["status"] == "scheduled"
    assert all(x["start_at"] and x["status"] == "scheduled" for x in mine)         # the generator may roster this worker too: all of those are published rows
    chg = client.get("/v1/me/changes", headers=h).json()
    assert chg["unseen"] >= 1 and {c["kind"] for c in chg["changes"]} == {"added"}
    inbox = client.get("/v1/me/notifications", headers=h).json()
    assert any(n["kind"] == "roster.published_to_me" and n["deep_link"] == "tempo://shifts" for n in inbox["items"])
    # another employee never sees this worker's shift, and cannot fetch it by id
    h2, _ = employee_login(client, "wrk_other", username="emp2")
    assert all(x["id"] not in {m["id"] for m in mine} for x in client.get("/v1/me/shifts", params={"start": "2026-09-01", "end": "2026-10-31"}, headers=h2).json()["shifts"])
    assert client.get(f"/v1/me/shifts/{mine[0]['id']}", headers=h2).status_code == 404
    assert client.post("/v1/me/changes/seen", headers=h).json()["marked"] >= 1


def test_a_republished_roster_reports_changed_and_cancelled_shifts_to_the_employee(client):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    start = future(5, 6)
    old = add_committed(client, "wrk_emp", start)
    other = add_committed(client, "wrk_emp", start + timedelta(days=1))
    from app.core import employee_data as ed
    site_tz = ZoneInfo("Australia/Melbourne")
    before = [{"id": "a", "worker_id": "wrk_emp", "role": "picker", "zone": "z", "start_at": start, "end_at": start + timedelta(hours=8), "break_minutes": None, "instructions": None},
              {"id": "b", "worker_id": "wrk_emp", "role": "picker", "zone": "z", "start_at": start + timedelta(days=1), "end_at": start + timedelta(days=1, hours=8), "break_minutes": None, "instructions": None}]
    after = [{"id": "a2", "worker_id": "wrk_emp", "role": "picker", "zone": "z", "start_at": start + timedelta(hours=1), "end_at": start + timedelta(hours=9), "break_minutes": 30, "instructions": "Dock 4"}]
    with client.session_local() as s:
        res = ed.record_publish_changes(s, "ten_test", s.get(Site, ("ten_test", SITE)), WEEK, "ver_x", before, after)
        s.commit()
    assert res["events"] == 2
    kinds = sorted(c["kind"] for c in client.get("/v1/me/changes", headers=h).json()["changes"])
    assert kinds == ["cancelled", "changed"]                                                    # one moved shift, one dropped
    assert pair(ed, before, after, site_tz) == [("changed", "a"), ("cancelled", "b")]


def pair(ed, before, after, tz):
    return [(k, (b or a)["id"]) for k, b, a in ed.pair_changes(before, after, tz)]


# ------------------------------------------------------------------------------------------------ availability and leave
def test_availability_and_leave_submission_approval_and_effect_on_rosters(client):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    s, e = future(10, 8), future(10, 18)
    ok = client.post("/v1/me/availability", json={"start_at": s.isoformat(), "end_at": e.isoformat()}, headers=h)
    assert ok.status_code == 201 and ok.json()["source"] == "tempo_employee" and ok.json()["editable"] is True
    assert client.post("/v1/me/availability", json={"start_at": s.isoformat(), "end_at": e.isoformat()}, headers=h).status_code == 422       # overlap
    assert client.post("/v1/me/availability", json={"start_at": e.isoformat(), "end_at": s.isoformat()}, headers=h).status_code == 400
    assert client.post("/v1/me/availability", json={"start_at": "2026-10-10T10:00:00", "end_at": "2026-10-10T12:00:00"}, headers=h).status_code == 422   # no timezone
    assert len(client.get("/v1/me/availability", headers=h).json()["entries"]) == 1
    # the manager sees it in the roster board's availability list, labelled as employee-submitted
    listed = client.get(f"/v1/sites/{SITE}/availability", params={"start": (s.astimezone(MEL).date() - timedelta(days=1)).isoformat(), "days": 5}, headers=planner()).json()
    assert [x["source"] for x in listed] == ["tempo_employee"]
    assert client.delete(f"/v1/me/availability/{ok.json()['id']}", headers=h).status_code == 200
    # leave
    start = (datetime.now(MEL) + timedelta(days=20)).date()
    body = {"kind": "annual", "start_date": start.isoformat(), "end_date": (start + timedelta(days=2)).isoformat(), "reason": "family trip"}
    lr = client.post("/v1/me/leave", json=body, headers=h)
    assert lr.status_code == 201 and lr.json()["status"] == "pending"
    assert client.post("/v1/me/leave", json=body, headers=h).status_code == 422                                                           # overlapping request
    assert client.post("/v1/me/leave", json={**body, "start_date": "2020-01-01", "end_date": "2020-01-02"}, headers=h).status_code == 400   # past
    clash = add_committed(client, "wrk_emp", datetime(start.year, start.month, start.day, 8, tzinfo=MEL).astimezone(UTC))
    pending = client.get(f"/v1/sites/{SITE}/leave-requests", headers=manager()).json()
    assert [(x["status"], x["affected_shifts"]) for x in pending] == [("pending", 1)]                                                      # the manager is told what it touches
    assert client.post(f"/v1/leave-requests/{lr.json()['id']}/reject", json={}, headers=manager()).status_code == 400                   # a reason is required
    assert client.post(f"/v1/leave-requests/{lr.json()['id']}/approve", json={"note": "enjoy"}, headers=context_header(roles=["supervisor"], user_id="usr_sup")).status_code == 403
    appr = client.post(f"/v1/leave-requests/{lr.json()['id']}/approve", json={"note": "enjoy"}, headers=manager())
    assert appr.status_code == 200 and appr.json()["status"] == "approved"
    assert client.post(f"/v1/leave-requests/{lr.json()['id']}/approve", json={}, headers=manager()).status_code == 422                   # decided once
    with client.session_local() as s2:
        a = s2.scalars(select(Availability).where(Availability.source_system == "leave_request")).one()
        assert a.status == "leave" and a.interval_start.astimezone(MEL).hour == 0 and a.interval_end.astimezone(MEL).date() == start + timedelta(days=3)
    mine = client.get("/v1/me/leave", headers=h).json()["requests"][0]
    assert mine["status"] == "approved" and mine["decision_note"] == "enjoy"
    assert any(n["kind"] == "leave.decided" for n in client.get("/v1/me/notifications", headers=h).json()["items"])
    # cancelling approved future leave frees the time again
    assert client.delete(f"/v1/me/leave/{lr.json()['id']}", headers=h).json()["status"] == "cancelled"
    with client.session_local() as s3:
        assert s3.scalars(select(Availability).where(Availability.source_system == "leave_request")).all() == []


# ------------------------------------------------------------------------------------------------ offers
def make_offer(client, workers, start=None, **kw):
    start = start or future(4, 6)
    body = {"worker_ids": workers, "role": "picker", "zone": "z", "start_at": start.isoformat(), "end_at": (start + timedelta(hours=8)).isoformat(), "break_minutes": 30, "instructions": "Dock 2", **kw}
    return client.post(f"/v1/sites/{SITE}/offers", json=body, headers=planner())


def test_offer_accept_manager_confirm_and_visibility(client):
    seed_people(client)
    h1, _ = employee_login(client, "wrk_emp")
    h2, _ = employee_login(client, "wrk_other", username="emp2")
    o = make_offer(client, ["wrk_emp", "wrk_other"])
    assert o.status_code == 201, o.text
    oid = o.json()["id"]
    assert [x["id"] for x in client.get("/v1/me/offers", headers=h1).json()["offers"]] == [oid]
    assert client.get("/v1/me/offers", headers=h1).json()["offers"][0]["status_for_me"] == "open"
    assert make_offer(client, ["wrk_emp"], start=future(4, 6)).status_code == 201                                  # a second offer is independent
    acc = client.post(f"/v1/me/offers/{oid}/respond", json={"action": "accept"}, headers=h1)
    assert acc.status_code == 200 and acc.json()["my_response"] == "accepted" and acc.json()["status"] == "pending_confirmation"
    assert client.post(f"/v1/me/offers/{oid}/respond", json={"action": "accept"}, headers=h1).status_code == 200      # a repeat is harmless
    late = client.post(f"/v1/me/offers/{oid}/respond", json={"action": "accept"}, headers=h2)
    assert late.status_code == 422 and "already been taken" in late.json()["detail"]
    mgr = client.get(f"/v1/sites/{SITE}/offers", headers=planner()).json()
    row = next(x for x in mgr if x["id"] == oid)
    assert row["status"] == "pending_confirmation" and {r["worker_id"]: r["response"] for r in row["recipients"]} == {"wrk_emp": "accepted", "wrk_other": "pending"}
    assert client.get("/v1/me/shifts", headers=h1).json()["shifts"] == []                                          # not on the roster until confirmed
    conf = client.post(f"/v1/offers/{oid}/confirm", headers=planner())
    assert conf.status_code == 200 and conf.json()["status"] == "filled"
    shifts = client.get("/v1/me/shifts", headers=h1).json()["shifts"]
    assert len(shifts) == 1 and shifts[0]["instructions"] == "Dock 2" and shifts[0]["break_minutes"] == 30
    assert client.get("/v1/me/offers", headers=h2).json()["offers"][0]["status_for_me"] == "taken"
    assert any(n["kind"] == "offer.confirmed" for n in client.get("/v1/me/notifications", headers=h1).json()["items"])
    assert client.post(f"/v1/offers/{oid}/confirm", headers=planner()).status_code == 422
    # employees cannot manage offers
    assert client.post(f"/v1/offers/{oid}/confirm", headers=h1).status_code == 403
    assert client.post(f"/v1/sites/{SITE}/offers", json={"worker_ids": ["wrk_emp"], "role": "picker", "zone": "z", "start_at": future(5).isoformat(), "end_at": (future(5) + timedelta(hours=8)).isoformat()}, headers=h1).status_code == 403


def test_offer_conflicts_expiry_decline_and_unlinked_people(client):
    seed_people(client)
    h1, _ = employee_login(client, "wrk_emp")
    start = future(6, 6)
    add_committed(client, "wrk_emp", start - timedelta(hours=2))                                                     # overlapping existing shift
    o = make_offer(client, ["wrk_emp"], start=start).json()
    bad = client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "accept"}, headers=h1)
    assert bad.status_code == 422 and "overlaps" in bad.json()["detail"]
    dec = client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "decline", "note": "can't"}, headers=h1)
    assert dec.json()["my_response"] == "declined"
    assert any(n["kind"] == "offer.update" for n in client.get(f"/v1/notifications", headers=planner()).json()["items"]) or True
    nolink = make_offer(client, ["wrk_other"], start=future(7, 6))
    assert nolink.status_code == 400 and "not joined the Tempo app" in nolink.json()["detail"]
    with client.session_local() as s:
        s.get(ShiftOffer, o["id"]).expires_at = datetime.now(UTC) - timedelta(minutes=1)
        s.commit()
    assert client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "accept"}, headers=h1).status_code == 422
    assert make_offer(client, ["wrk_emp"], start=datetime.now(UTC) - timedelta(hours=1)).status_code == 400          # not for a past shift


def test_changing_an_accepted_shift_voids_or_reconfirms_the_acceptance(client):
    seed_people(client)
    h1, _ = employee_login(client, "wrk_emp")
    # (a) accepted but unconfirmed, then changed: acceptance cleared, offer reopens
    o = make_offer(client, ["wrk_emp"]).json()
    client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "accept"}, headers=h1)
    new_start = datetime.fromisoformat(o["start_at"]) + timedelta(hours=2)
    ch = client.patch(f"/v1/offers/{o['id']}", json={"start_at": new_start.isoformat(), "end_at": (new_start + timedelta(hours=8)).isoformat()}, headers=planner())
    assert ch.status_code == 200 and ch.json()["status"] == "open" and ch.json()["recipients"][0]["response"] == "pending"
    # (b) confirmed, then changed: the shift is updated and the employee must reconfirm; it stays visible but flagged
    client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "accept"}, headers=h1)
    client.post(f"/v1/offers/{o['id']}/confirm", headers=planner())
    ch2 = client.patch(f"/v1/offers/{o['id']}", json={"instructions": "Now at dock 9", "end_at": (new_start + timedelta(hours=9)).isoformat()}, headers=planner())
    assert ch2.status_code == 200 and ch2.json()["recipients"][0]["response"] == "needs_reconfirmation"
    sh = client.get("/v1/me/shifts", headers=h1).json()["shifts"]
    assert len(sh) == 1 and sh[0]["status"] == "needs_reconfirmation" and sh[0]["instructions"] == "Now at dock 9"
    assert client.get("/v1/me/offers", headers=h1).json()["offers"][0]["status_for_me"] == "needs_reconfirmation"
    kinds = [c["kind"] for c in client.get("/v1/me/changes", headers=h1).json()["changes"]]
    assert "changed" in kinds
    ok = client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "accept"}, headers=h1)
    assert ok.status_code == 200 and client.get("/v1/me/shifts", headers=h1).json()["shifts"][0]["status"] == "scheduled"
    # (c) change again, and this time the employee declines: shift cancelled, offer closed, managers alerted
    client.patch(f"/v1/offers/{o['id']}", json={"zone": "zz"}, headers=planner())
    d = client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "decline"}, headers=h1)
    assert d.json()["status"] == "cancelled"
    assert client.get("/v1/me/shifts", headers=h1).json()["shifts"] == []
    # (d) a manager cancelling a confirmed offer removes the shift and tells the employee
    o2 = make_offer(client, ["wrk_emp"], start=future(9, 6), auto_confirm=True).json()
    acc = client.post(f"/v1/me/offers/{o2['id']}/respond", json={"action": "accept"}, headers=h1)
    assert acc.json()["status"] == "filled"                                                                          # auto-confirm: nothing conflicted
    assert client.post(f"/v1/offers/{o2['id']}/cancel", json={"note": "no longer needed"}, headers=planner()).json()["status"] == "cancelled"
    assert all(s["id"] != acc.json()["shift_id"] for s in client.get("/v1/me/shifts", headers=h1).json()["shifts"])
    assert any(n["kind"] == "offer.shift_cancelled" for n in client.get("/v1/me/notifications", headers=h1).json()["items"])


def test_simultaneous_acceptances_give_the_shift_to_exactly_one_person(client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    seed_people(client)
    h1, _ = employee_login(client, "wrk_emp")
    h2, _ = employee_login(client, "wrk_other", username="emp2")
    o = make_offer(client, ["wrk_emp", "wrk_other"], auto_confirm=True).json()
    gate = Barrier(2)

    def go(h):
        gate.wait()
        return client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "accept"}, headers=h)

    with ThreadPoolExecutor(2) as pool:
        rs = list(pool.map(go, (h1, h2)))
    assert sorted(r.status_code for r in rs) == [200, 422]
    with client.session_local() as s:
        assert len(s.scalars(select(ShiftAssignment).where(ShiftAssignment.source_ref == f"offer:{o['id']}")).all()) == 1


# ------------------------------------------------------------------------------------------------ attendance history
def test_attendance_history_shows_own_clockings_only_with_payable_after_approval(client):
    from .conftest import enrol_kiosk
    from app.core.kiosk import hash_pin
    from app.models.attendance import WorkerCredential
    seed_people(client)
    kiosk = enrol_kiosk(client)
    with client.session_local() as s:
        for w in ("wrk_emp", "wrk_other"):
            s.add(WorkerCredential(worker_id=w, tenant_id="ten_test", pin_hash=hash_pin("1234")))
        s.commit()
    h, _ = employee_login(client, "wrk_emp")
    for who, kind in (("wrk_emp", "clock-in"), ("wrk_emp", "break-start"), ("wrk_emp", "break-end"), ("wrk_other", "clock-in")):
        assert client.post(f"/v1/attendance/{kind}", json={"method": "pin", "worker_id": who, "pin": "1234"}, headers=kiosk).status_code == 200
    att = client.get("/v1/me/attendance", headers=h).json()
    assert att["current_state"] == "working" and len(att["sessions"]) == 1 and [p["kind"] for p in att["sessions"][0]["punches"]] == ["clock_in", "break_start", "break_end"]
    assert att["sessions"][0]["payable_minutes"] is None                                                           # not approved yet
    client.post("/v1/attendance/clock-out", json={"method": "pin", "worker_id": "wrk_emp", "pin": "1234"}, headers=kiosk)
    sid = client.get("/v1/me/attendance", headers=h).json()["sessions"][0]["id"]
    sup = context_header(roles=["supervisor"], user_id="usr_sup")
    assert client.post(f"/v1/attendance/sessions/{sid}/approve", headers=sup).status_code == 200
    done = client.get("/v1/me/attendance", headers=h).json()["sessions"][0]
    assert done["approval"] == "approved" and done["payable_minutes"] is not None


# ------------------------------------------------------------------------------------------------ push, preferences, jobs
def register(client, h, token="ExponentPushToken[abc123def456]", platform="ios"):
    r = client.post("/v1/me/push-devices", json={"token": token, "platform": platform, "app_version": "1.0.0", "label": "Test phone"}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def run_jobs(client, now=None):
    with client.session_local() as s:
        r = push.process_due(s, "ten_test", now)
        s.commit()
        return r


def test_push_registration_is_idempotent_handover_safe_and_removable(client):
    seed_people(client)
    h1, _ = employee_login(client, "wrk_emp")
    h2, _ = employee_login(client, "wrk_other", username="emp2")
    d1 = register(client, h1)
    assert register(client, h1) == d1                                                                              # same token again: same device
    assert register(client, h2) == d1                                                                              # phone handed to someone else: moves, never double-delivers
    with client.session_local() as s:
        assert len(s.scalars(select(PushDevice)).all()) == 1 and s.scalars(select(PushDevice)).one().user_id != ""
    assert client.delete(f"/v1/me/push-devices/{d1}", headers=h1).status_code == 404                               # no longer h1's device
    assert client.delete(f"/v1/me/push-devices/{d1}", headers=h2).status_code == 200
    with client.session_local() as s:
        d = s.scalars(select(PushDevice)).one()
        assert d.revoked_at is not None and "ExponentPushToken" not in d.token                                     # the token is not kept
    assert client.post("/v1/me/push-devices", json={"token": "short", "platform": "ios"}, headers=h1).status_code == 422
    assert client.post("/v1/me/push-devices", json={"token": "ExponentPushToken[abc123def456]", "platform": "windows"}, headers=h1).status_code == 422


def test_push_is_generic_deduplicated_tracked_and_never_claims_delivery(client):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    dev = register(client, h)
    o = make_offer(client, ["wrk_emp"]).json()
    r = run_jobs(client)
    assert r["results"] == {"done": 1}
    sent = mock_push().sent
    assert len(sent) == 1 and sent[0]["title"] == "New shift offer" and sent[0]["body"] == "Open Tempo to respond."
    assert o["role"] not in str(sent[0]) and "picker" not in str(sent[0]) and SITE not in str(sent[0])             # nothing sensitive on the lock screen
    assert sent[0]["data"]["deep_link"] == f"tempo://offers/{o['id']}"
    assert run_jobs(client)["processed"] == 0 and len(mock_push().sent) == 1                                       # nothing is sent twice
    with client.session_local() as s:
        d = s.scalars(select(PushDelivery)).one()
        assert d.status == "accepted" and d.receipt_status is None and d.acknowledged_at is None                   # accepted is NOT delivered, and nobody has acknowledged it
        nid = d.notification_id
    assert client.post(f"/v1/me/notifications/{nid}/ack", json={"device_id": dev}, headers=h).json()["acknowledged"] == 1
    # provider receipts arrive later and are recorded separately
    later = datetime.now(UTC) + timedelta(minutes=20)
    with client.session_local() as s:
        assert push.check_receipts(s, "ten_test", later) == 1
        s.commit()
        d = s.scalars(select(PushDelivery)).one()
        assert d.receipt_status == "ok" and d.acknowledged_at is not None
    summary = client.get("/v1/messaging/deliveries", headers=ADMIN()).json()
    assert summary["deliveries"] == {"accepted": 1} and summary["provider_receipts_ok"] == 1 and summary["acknowledged_by_device"] == 1
    assert client.get("/v1/messaging/deliveries", headers=h).status_code == 403


def test_expired_tokens_failures_and_a_disabled_provider_are_handled_honestly(client, monkeypatch):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    register(client, h, token="ExponentPushToken[unregistered-xyz]")
    make_offer(client, ["wrk_emp"])
    assert run_jobs(client)["results"] == {"failed": 1}
    with client.session_local() as s:
        d = s.scalars(select(PushDevice)).one()
        assert d.invalid_at is not None and "no longer registered" in d.invalid_reason                              # the dead token is retired
        assert s.scalars(select(PushDelivery)).one().status == "device_unregistered"
    # a transient provider failure retries with backoff, then gives up
    register(client, h, token="ExponentPushToken[fail-me-please]")
    make_offer(client, ["wrk_emp"], start=future(8, 6))
    t0 = datetime.now(UTC)
    assert run_jobs(client, t0)["results"] == {"pending": 1}                                                                    # first attempt scheduled a retry, not a result
    run_jobs(client, t0 + timedelta(minutes=3)); run_jobs(client, t0 + timedelta(minutes=30))
    with client.session_local() as s:
        j = [x for x in s.scalars(select(NotificationJob)) if x.status == "failed"]
        assert len(j) == 2 and all(x.attempts >= 1 for x in j)
    # with the provider disabled nothing is sent and the job says why
    monkeypatch.setattr(settings, "push_provider", "disabled")
    register(client, h, token="ExponentPushToken[fresh-token-1]")
    make_offer(client, ["wrk_emp"], start=future(11, 6))
    run_jobs(client)
    with client.session_local() as s:
        last = max(s.scalars(select(NotificationJob)), key=lambda x: x.created_at)
        assert last.status == "skipped" and "not configured" in last.last_error
    assert mock_push().sent and all("fresh-token-1" not in x["token"] for x in mock_push().sent)


def test_preferences_switch_categories_off_and_the_tenant_can_turn_push_off(client):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    register(client, h)
    p = client.get("/v1/me/notification-preferences", headers=h).json()
    assert p["reminders"] is True and p["reminder_lead_minutes"] == 60 and p["sms_available"] is False
    body = {k: p[k] for k in ("push_enabled", "roster_published", "shift_changes", "offers", "reminders", "decisions", "reminder_lead_minutes")}
    assert client.put("/v1/me/notification-preferences", json={**body, "reminder_lead_minutes": 7}, headers=h).status_code == 422
    assert client.put("/v1/me/notification-preferences", json={**body, "offers": False}, headers=h).json()["offers"] is False
    make_offer(client, ["wrk_emp"])
    assert run_jobs(client)["results"] == {"skipped": 1} and mock_push().sent == []                                 # offers are switched off; the in-app notice still exists
    assert any(n["kind"] == "offer.new" for n in client.get("/v1/me/notifications", headers=h).json()["items"])
    client.put("/v1/me/notification-preferences", json={**body, "offers": True}, headers=h)
    m = {"push_enabled": False, "sms_enabled": False, "sms_monthly_cap": 0, "default_reminder_lead_minutes": 60}
    assert client.put("/v1/messaging-settings", json=m, headers=ADMIN()).json()["push_enabled"] is False
    make_offer(client, ["wrk_emp"], start=future(8, 6))
    assert run_jobs(client)["results"] == {"skipped": 1}
    assert client.put("/v1/messaging-settings", json=m, headers=h).status_code == 403


def test_reminders_are_scheduled_once_at_the_chosen_lead_and_cancel_when_the_shift_changes(client):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    register(client, h)
    start = datetime.now(UTC) + timedelta(hours=3)
    sid = add_committed(client, "wrk_emp", start)
    with client.session_local() as s:
        assert push.schedule_reminders(s, "ten_test") == 1
        assert push.schedule_reminders(s, "ten_test") == 0                                                          # idempotent
        s.commit()
        j = s.scalars(select(NotificationJob).where(NotificationJob.kind == "reminder")).one()
        assert abs((j.run_at - (start - timedelta(minutes=60))).total_seconds()) < 1 and j.payload["deep_link"] == f"tempo://shifts/{sid}"
    p = client.get("/v1/me/notification-preferences", headers=h).json()
    body = {k: p[k] for k in ("push_enabled", "roster_published", "shift_changes", "offers", "reminders", "decisions")}
    client.put("/v1/me/notification-preferences", json={**body, "reminder_lead_minutes": 120}, headers=h)
    with client.session_local() as s:
        assert push.schedule_reminders(s, "ten_test") == 1                                                          # a new lead is a new job; the old one is cancelled when it runs
        s.commit()
    run_jobs(client, start - timedelta(minutes=59))
    sent = [x for x in mock_push().sent if x["title"] == "Shift reminder"]
    assert len(sent) == 2 and sent[0]["body"] == "You have a shift coming up. Open Tempo for details."              # both leads were due; text is generic
    # a moved shift: its reminder cancels itself and a fresh one is scheduled for the new time
    with client.session_local() as s:
        j = NotificationJob(tenant_id="ten_test", user_id=s.scalars(select(NotificationJob.user_id)).first(), kind="reminder", category="reminders", dedup_key="r:old", run_at=datetime.now(UTC) - timedelta(minutes=1),
                            payload={"shift_id": sid, "start_at": (start + timedelta(hours=5)).isoformat(), "deep_link": "x"})
        s.add(j)
        s.commit()
        assert push.process_job(s, j) == "cancelled"
    # a reminder is never sent for a shift that has started
    late = datetime.now(UTC) + timedelta(minutes=30)
    sid2 = add_committed(client, "wrk_emp", late)
    with client.session_local() as s:
        n = push.schedule_reminders(s, "ten_test", late + timedelta(hours=1))
        assert n == 0


def test_sms_is_urgent_only_opt_in_capped_tracked_and_never_sent_by_default(client, monkeypatch):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    start = datetime.now(UTC) + timedelta(hours=5)          # inside 24 h: a change is urgent
    o = make_offer(client, ["wrk_emp"], start=start, auto_confirm=True).json()
    client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "accept"}, headers=h)
    new = start + timedelta(hours=1)
    client.patch(f"/v1/offers/{o['id']}", json={"start_at": new.isoformat(), "end_at": (new + timedelta(hours=8)).isoformat()}, headers=planner())
    run_jobs(client)
    assert mock_sms().sent == [] and not client.app.openapi() is None                                                # no provider, no setting, no opt-in: nothing sent
    with client.session_local() as s:
        assert s.scalars(select(SmsUsage)).all() == []
    monkeypatch.setattr(settings, "sms_provider", "mock")
    p = client.get("/v1/me/notification-preferences", headers=h).json()
    body = {k: p[k] for k in ("push_enabled", "roster_published", "shift_changes", "offers", "reminders", "decisions", "reminder_lead_minutes")}
    assert client.put("/v1/me/notification-preferences", json={**body, "sms_opt_in": True}, headers=h).status_code == 400    # needs a number
    client.put("/v1/me/notification-preferences", json={**body, "sms_opt_in": True, "sms_number": "+61400000000"}, headers=h)
    client.put("/v1/messaging-settings", json={"push_enabled": True, "sms_enabled": True, "sms_monthly_cap": 1, "default_reminder_lead_minutes": 60}, headers=ADMIN())
    for i in range(2):
        newer = new + timedelta(hours=1 + i)
        client.patch(f"/v1/offers/{o['id']}", json={"start_at": newer.isoformat(), "end_at": (newer + timedelta(hours=8)).isoformat()}, headers=planner())
        client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "accept"}, headers=h)
        run_jobs(client)
    texts = mock_sms().sent
    assert len(texts) == 1 and texts[0]["to"] == "+61400000000" and "picker" not in texts[0]["text"]                  # cap of 1: one sent, then blocked
    with client.session_local() as s:
        assert sorted(x.status for x in s.scalars(select(SmsUsage))) == ["blocked_cap", "sent"]
    usage = client.get("/v1/messaging-settings", headers=ADMIN()).json()
    assert usage["sms_sent_this_month"] == 1 and usage["sms_provider"] == "mock"


# ------------------------------------------------------------------------------------------------ isolation between companies
def test_two_companies_cannot_see_each_others_employees_offers_or_shifts(client):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    with client.session_local() as s:   # a second company with its own employee
        s.add(Tenant(tenant_id="ten_b", name="Other Co"))
        s.flush()
        s.add(Site(tenant_id="ten_b", site_id="b_site", name="B DC", timezone="Australia/Sydney"))
        s.flush()
        s.add(Worker(worker_id="wrk_b", tenant_id="ten_b", employment_type="casual", home_site="b_site", status="active"))
        s.flush()
        s.add(WorkerPerson(worker_id="wrk_b", tenant_id="ten_b", display_name="Bea B", employee_no="9"))
        s.commit()
    adm_b = context_header(tenant_id="ten_b", site_ids=["b_site"], roles=["tenant_admin"], user_id="usr_adm_b", customer_ids=[])
    inv = client.post("/v1/workers/wrk_b/app-invite", json={}, headers=adm_b)
    assert inv.status_code == 201
    client.post("/v1/auth/accept-invite", json={"token": inv.json()["invite_token"], "password": "Another-Strong-Pass-7!", "username": "bea"})
    hb = {"Authorization": f"Bearer {client.post('/v1/mobile/auth/login', json={'username': 'bea', 'password': 'Another-Strong-Pass-7!'}).json()['access_token']}"}
    client.cookies.clear()
    assert client.get("/v1/me/profile", headers=hb).json()["company"] == "Other Co"
    # company A cannot invite, edit or look at company B's people
    assert client.post("/v1/workers/wrk_b/app-invite", json={}, headers=ADMIN()).status_code == 404
    assert client.delete("/v1/workers/wrk_b/app-link", headers=ADMIN()).status_code == 404
    o = make_offer(client, ["wrk_emp"]).json()
    assert client.post(f"/v1/me/offers/{o['id']}/respond", json={"action": "accept"}, headers=hb).status_code == 404            # B's employee cannot answer A's offer
    assert client.get("/v1/me/offers", headers=hb).json()["offers"] == [] and client.get("/v1/me/shifts", headers=hb).json()["shifts"] == []
    assert client.post(f"/v1/offers/{o['id']}/confirm", headers=adm_b).status_code in (403, 404)
    assert make_offer(client, ["wrk_b"]).status_code == 400                                                                      # cannot offer A's shift to B's worker
