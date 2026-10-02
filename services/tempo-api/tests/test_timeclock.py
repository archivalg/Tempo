"""Roadmap M2: internal time and attendance — break capture, duplicates, policy, supervisor list, corrections, revisions, payroll CSV."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.core import timeclock
from app.errors import AttendanceStateConflict
from app.models.attendance import AttendancePolicy, AttendancePunch, AttendanceRevision, WorkerCredential
from app.models.canonical import AttendanceSession, ShiftAssignment, Worker
from app.models.directory import Site, WorkerPerson

from .conftest import context_header, enrol_kiosk

SITE = "site_mel_01"
UTC = timezone.utc


def supervisor(**kw):
    return context_header(roles=["supervisor"], user_id="usr_sup", **kw)


def manager(**kw):
    return context_header(roles=["operations_manager"], user_id="usr_mgr", **kw)


def admin(**kw):
    return context_header(roles=["tenant_admin"], user_id="usr_admin", **kw)


@pytest.fixture()
def kit(client):
    """A site (Melbourne), two workers with PIN credentials, an enrolled kiosk."""
    with client.session_local() as s:
        enrol = enrol_kiosk(client)
        s.add(Site(tenant_id="ten_test", site_id=SITE, name="Test DC", timezone="Australia/Melbourne", operating_mode="standalone"))
        s.flush()
        for wid, no, name in (("wrk_a", "1001", "Alex Aardvark"), ("wrk_b", "1002", "Bo Bandicoot")):
            s.add(Worker(worker_id=wid, tenant_id="ten_test", employment_type="permanent", home_site=SITE, status="active"))
            s.flush()
            s.add(WorkerPerson(worker_id=wid, tenant_id="ten_test", display_name=name, employee_no=no))
            s.add(WorkerCredential(worker_id=wid, tenant_id="ten_test", pin_hash=timeclock_hash("1234")))
        s.commit()
    return enrol


def timeclock_hash(pin):
    from app.core.kiosk import hash_pin
    return hash_pin(pin)


def tap(client, kit, path, worker="wrk_a", pin="1234"):
    return client.post(f"/v1/attendance/{path}", json={"method": "pin", "worker_id": worker, "pin": pin}, headers=kit)


def core(client, action, worker="wrk_a", at=None):
    """Drive the state machine with a chosen clock (owner connection; RLS is not what is under test here)."""
    with client.session_local() as s:
        w = s.get(Worker, worker)
        r = timeclock.punch(s, "ten_test", SITE, "dev", w, action, now=at)
        s.commit()
        return r.duplicate, r.session.id


def session_row(client, sid):
    with client.session_local() as s:
        x = s.get(AttendanceSession, sid)
        s.expunge(x)
        return x


def seed_closed(client, worker, start, end, brk=0.0, approval="pending", shift=None):
    with client.session_local() as s:
        x = AttendanceSession(tenant_id="ten_test", worker_id=worker, start_at=start, end_at=end, breaks_minutes=brk, approval=approval, source_system="tempo_native",
                              site_id=SITE, state="closed", rostered_shift_id=shift)
        s.add(x)
        s.commit()
        return x.id


# ---------------------------------------------------------------- capture
def test_clock_break_cycle_over_the_kiosk_api(client, kit):
    who = client.post("/v1/attendance/whoami", json={"method": "pin", "worker_id": "wrk_a", "pin": "1234"}, headers=kit).json()
    assert who["state"] == "not_clocked_in" and who["allowed_actions"] == ["clock_in"]
    assert tap(client, kit, "clock-in").json()["state"] == "working"
    who = client.post("/v1/attendance/whoami", json={"method": "pin", "worker_id": "wrk_a", "pin": "1234"}, headers=kit).json()
    assert who["allowed_actions"] == ["break_start", "clock_out"]
    assert tap(client, kit, "break-start").json()["state"] == "on_break"
    assert tap(client, kit, "break-end").json()["state"] == "working"
    out = tap(client, kit, "clock-out").json()
    assert out["state"] == "closed" and out["duplicate"] is False
    with client.session_local() as s:
        kinds = [p.kind for p in s.scalars(select(AttendancePunch).order_by(AttendancePunch.at, AttendancePunch.id))]
    assert kinds == ["clock_in", "break_start", "break_end", "clock_out"]


def test_repeat_tap_returns_the_first_result_and_records_nothing_new(client, kit):
    a = tap(client, kit, "clock-in").json()
    b = tap(client, kit, "clock-in").json()
    assert a["duplicate"] is False and b["duplicate"] is True and a["attendance_session_id"] == b["attendance_session_id"] and a["clocked_in_at"] == b["clocked_in_at"]
    tap(client, kit, "break-start")
    assert tap(client, kit, "break-start").json()["duplicate"] is True
    tap(client, kit, "break-end")
    tap(client, kit, "clock-out")
    assert tap(client, kit, "clock-out").json()["duplicate"] is True
    with client.session_local() as s:
        assert len(s.scalars(select(AttendancePunch)).all()) == 4 and len(s.scalars(select(AttendanceSession)).all()) == 1


def test_state_machine_refuses_out_of_order_punches(client, kit):
    t0 = datetime.now(UTC) - timedelta(hours=3)
    assert tap(client, kit, "break-start").status_code == 409  # not clocked in
    assert tap(client, kit, "clock-out").status_code == 409
    core(client, "clock_in", at=t0)
    with pytest.raises(AttendanceStateConflict):  # a later clock-in, past the duplicate window, is not silently a second session
        core(client, "clock_in", at=t0 + timedelta(minutes=5))
    with pytest.raises(AttendanceStateConflict):
        core(client, "break_end", at=t0 + timedelta(minutes=6))
    core(client, "break_start", at=t0 + timedelta(hours=1))
    with pytest.raises(AttendanceStateConflict):
        core(client, "break_start", at=t0 + timedelta(hours=1, minutes=5))


def test_clock_out_while_on_break_ends_the_break_and_says_so(client, kit):
    t0 = datetime.now(UTC) - timedelta(hours=4)
    core(client, "clock_in", at=t0)
    core(client, "break_start", at=t0 + timedelta(hours=2))
    _, sid = core(client, "clock_out", at=t0 + timedelta(hours=2, minutes=30))
    x = session_row(client, sid)
    assert x.state == "closed" and x.breaks_minutes == 30
    with client.session_local() as s:
        auto = s.scalars(select(AttendancePunch).where(AttendancePunch.kind == "break_end")).one()
    assert auto.source == "auto" and "clock-out" in auto.note


def test_only_one_open_native_session_per_worker_is_enforced_by_the_database(client, kit):
    core(client, "clock_in")
    with client.session_local() as s:
        s.add(AttendanceSession(tenant_id="ten_test", worker_id="wrk_a", start_at=datetime.now(UTC), approval="pending", source_system="tempo_native", site_id=SITE, state="working"))
        with pytest.raises(IntegrityError):
            s.commit()


def test_punches_and_revisions_cannot_be_deleted_by_the_app(client, kit):
    tap(client, kit, "clock-in")
    with client.app_session_local() as s:
        s.execute(text("SELECT set_config('app.tenant_id','ten_test', true)"))
        with pytest.raises(ProgrammingError):
            s.execute(text("DELETE FROM attendance_punch"))


def test_overnight_shift_is_matched_and_hours_span_midnight(client, kit):
    local = datetime(2026, 9, 14, 22, 0, tzinfo=timezone(timedelta(hours=10)))  # a Monday night shift, 22:00 to 06:00
    start, end = local.astimezone(UTC), (local + timedelta(hours=8)).astimezone(UTC)
    with client.session_local() as s:
        sh = ShiftAssignment(tenant_id="ten_test", worker_id="wrk_a", role="picker", zone="z1", start_at=start, end_at=end, status="committed")
        s.add(sh)
        s.commit()
        shift_id = sh.shift_id
    _, sid = core(client, "clock_in", at=start - timedelta(minutes=10))
    core(client, "break_start", at=start + timedelta(hours=3))
    core(client, "break_end", at=start + timedelta(hours=3, minutes=30))
    core(client, "clock_out", at=end + timedelta(minutes=5))
    x = session_row(client, sid)
    assert x.rostered_shift_id == shift_id
    with client.session_local() as s:
        h = timeclock.hours(s.get(AttendanceSession, sid), None, timeclock.get_policy(s, "ten_test", SITE), end + timedelta(hours=1))
    assert h["worked_minutes"] == 8 * 60 + 15 and h["break_minutes"] == 30 and h["unpaid_break_minutes"] == 30 and h["payable_minutes"] == 8 * 60 + 15 - 30


def test_paid_breaks_and_rounding_are_explicit_site_policy(client, kit):
    t0 = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    sid = seed_closed(client, "wrk_a", t0, t0 + timedelta(hours=8, minutes=8), brk=30)
    with client.session_local() as s:
        x = s.get(AttendanceSession, sid)
        d = timeclock.get_policy(s, "ten_test", SITE)
        assert timeclock.hours(x, None, d, t0)["payable_minutes"] == 8 * 60 + 8 - 30  # defaults: unpaid breaks, no rounding
        paid = AttendancePolicy(tenant_id="ten_test", site_id=SITE, breaks_paid=True, rounding_minutes=15, rounding_mode="nearest")
        h = timeclock.hours(x, None, paid, t0)
        assert h["unpaid_break_minutes"] == 0 and h["worked_minutes"] == 488 and h["payable_minutes"] == 495 and h["rounded"] is True  # 488 -> nearest 15 = 495
        assert timeclock.hours(x, None, AttendancePolicy(tenant_id="ten_test", site_id=SITE, breaks_paid=True, rounding_minutes=15, rounding_mode="down"), t0)["payable_minutes"] == 480


def test_policy_can_be_read_by_anyone_in_scope_and_set_only_by_a_configurer(client, kit):
    d = client.get(f"/v1/sites/{SITE}/attendance-policy", headers=supervisor()).json()
    assert d["is_default"] is True and d["breaks_paid"] is False
    body = {"breaks_paid": True, "rounding_minutes": 15, "rounding_mode": "nearest", "duplicate_window_seconds": 30, "late_grace_minutes": 5, "missing_punch_after_hours": 14, "excessive_hours": 12}
    assert client.put(f"/v1/sites/{SITE}/attendance-policy", json=body, headers=supervisor()).status_code == 403
    assert client.put(f"/v1/sites/{SITE}/attendance-policy", json={**body, "rounding_minutes": 7}, headers=admin()).status_code == 422
    ok = client.put(f"/v1/sites/{SITE}/attendance-policy", json=body, headers=admin())
    assert ok.status_code == 200 and ok.json()["is_default"] is False and ok.json()["updated_by"].startswith("usr_admin")
    assert client.get(f"/v1/sites/{SITE}/attendance-policy", headers=supervisor()).json()["rounding_minutes"] == 15


# ---------------------------------------------------------------- supervisor daily list
def test_daily_list_surfaces_each_exception(client, kit):
    """Uses yesterday (site-local) so the result does not depend on the time of day the suite runs."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Australia/Melbourne")
    day = (datetime.now(tz).date() - timedelta(days=1))
    at = lambda h, m=0: datetime(day.year, day.month, day.day, h, m, tzinfo=tz).astimezone(UTC)  # noqa: E731
    with client.session_local() as s:
        for wid in ("wrk_c", "wrk_d", "wrk_e"):
            s.add(Worker(worker_id=wid, tenant_id="ten_test", employment_type="casual", home_site=SITE, status="active"))
        s.flush()
        late_sh = ShiftAssignment(tenant_id="ten_test", worker_id="wrk_a", role="picker", zone="z", start_at=at(6), end_at=at(14), status="committed")
        ns_sh = ShiftAssignment(tenant_id="ten_test", worker_id="wrk_b", role="picker", zone="z", start_at=at(6), end_at=at(14), status="committed")
        s.add_all([late_sh, ns_sh])
        s.flush()
        late_id = late_sh.shift_id
        s.commit()
    with client.session_local() as s:   # wrk_a clocks in 40 minutes late; wrk_c is unrostered and never clocked out; wrk_d has a 13 hour unrostered day
        s.add_all([
            AttendanceSession(tenant_id="ten_test", worker_id="wrk_a", start_at=at(6, 40), end_at=at(14, 1), approval="pending", source_system="tempo_native", site_id=SITE, state="closed", rostered_shift_id=late_id),
            AttendanceSession(tenant_id="ten_test", worker_id="wrk_c", start_at=at(3), approval="pending", source_system="tempo_native", site_id=SITE, state="working"),
            AttendanceSession(tenant_id="ten_test", worker_id="wrk_d", start_at=at(2), end_at=at(15), approval="pending", source_system="tempo_native", site_id=SITE, state="closed")])
        s.commit()
    r = client.get(f"/v1/sites/{SITE}/attendance/daily", params={"date": day.isoformat()}, headers=supervisor())
    assert r.status_code == 200, r.text
    rows = {x["worker_id"]: x for x in r.json()["rows"]}
    assert rows["wrk_a"]["flags"] == ["late"] and rows["wrk_a"]["minutes_late"] == 40
    assert rows["wrk_b"]["flags"] == ["no_show"] and rows["wrk_b"]["state"] == "no_show"
    assert {"unrostered", "missing_clock_out"} <= set(rows["wrk_c"]["flags"])
    assert "excessive_hours" in rows["wrk_d"]["flags"] and "unrostered" in rows["wrk_d"]["flags"]
    counts = r.json()["counts"]
    assert counts["no_show"] == 1 and counts["late"] == 1 and counts["unrostered"] == 2
    # names only with labour.worker_names; the supervisor role has it, an analyst does not
    assert rows["wrk_b"]["label"] == "Bo Bandicoot"
    plain = client.get(f"/v1/sites/{SITE}/attendance/daily", params={"date": day.isoformat()}, headers=context_header(roles=["analyst"], user_id="usr_an")).json()["rows"]
    assert all("Bandicoot" not in x["label"] for x in plain)


def test_kiosk_device_cannot_reach_manager_screens(client, kit):
    for path in (f"/v1/sites/{SITE}/attendance/daily", f"/v1/sites/{SITE}/attendance-policy", f"/v1/sites/{SITE}/clock-credentials", f"/v1/sites/{SITE}/exports/payroll-timesheets.csv"):
        assert client.get(path, headers=kit).status_code in (401, 403), path


# ---------------------------------------------------------------- corrections, approval, revisions
def _session(client, hours_ago=20, length=8, brk=30.0):
    start = datetime.now(UTC) - timedelta(hours=hours_ago)
    return seed_closed(client, "wrk_a", start, start + timedelta(hours=length), brk=brk), start


def test_correction_needs_a_second_person_and_leaves_the_original_untouched(client, kit):
    sid, start = _session(client)
    req = {"requested_start": (start - timedelta(minutes=20)).isoformat(), "requested_end": (start + timedelta(hours=8, minutes=15)).isoformat(), "requested_break_minutes": 45, "reason": "forgot to punch early"}
    both = context_header(roles=["supervisor", "operations_manager"], user_id="usr_sup")  # the same person holds both roles (and, in tests, must use one header)
    r = client.post(f"/v1/attendance/sessions/{sid}/adjustments", json=req, headers=both)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert client.post(f"/v1/attendance/sessions/{sid}/approve", headers=supervisor()).status_code == 422  # a pending correction blocks approval
    assert client.post(f"/v1/attendance/adjustments/{aid}/approve", json={}, headers=both).status_code == 403  # not their own
    assert client.post(f"/v1/attendance/adjustments/{aid}/approve", json={"note": "checked CCTV"}, headers=manager()).status_code == 200
    x = session_row(client, sid)
    assert x.start_at == start and x.breaks_minutes == 30  # the recorded session still shows what was punched
    assert client.post(f"/v1/attendance/sessions/{sid}/approve", headers=supervisor()).status_code == 200
    ts = client.get(f"/v1/sites/{SITE}/timesheets", headers=supervisor(), params={"start": (start - timedelta(days=1)).date().isoformat(), "days": 3}).json()
    row = next(s for s in ts["sessions"] if s["session_id"] == sid)
    assert row["worked_hours"] == 8.58 and row["break_hours"] == 0.75 and row["payable_hours"] == 7.83 and row["revision"] == 1 and row["approved_by"].startswith("usr_sup")
    orig = client.get(f"/v1/attendance/sessions/{sid}/history", headers=supervisor()).json()["corrections"][0]["original"]
    assert orig["breaks_minutes"] == 30 and orig["state"] == "closed"


def test_open_session_with_a_missing_clock_out_is_closed_by_an_approved_correction(client, kit):
    t0 = datetime.now(UTC) - timedelta(hours=20)
    core(client, "clock_in", at=t0)
    sid = session_row(client, core(client, "break_start", at=t0 + timedelta(hours=4))[1]).id  # went on a break and never came back
    r = client.post(f"/v1/attendance/sessions/{sid}/adjustments", json={"requested_start": t0.isoformat(), "requested_end": (t0 + timedelta(hours=9)).isoformat(), "requested_break_minutes": 30,
                                                                         "reason": "left at 5pm, forgot to clock out"}, headers=supervisor())
    assert r.status_code == 201
    client.post(f"/v1/attendance/adjustments/{r.json()['id']}/approve", json={}, headers=manager())
    x = session_row(client, sid)
    assert x.state == "closed" and x.end_at is None  # no clock-out punch is invented
    assert tap(client, kit, "clock-in").status_code == 200  # and the worker is free to clock in again
    with client.session_local() as s:
        assert [p.kind for p in s.scalars(select(AttendancePunch).where(AttendancePunch.session_id == sid).order_by(AttendancePunch.at))] == ["clock_in", "break_start"]


def test_reopening_an_approved_timesheet_records_a_revision(client, kit):
    sid, start = _session(client)
    assert client.post(f"/v1/attendance/sessions/{sid}/approve", headers=supervisor()).status_code == 200
    assert client.post(f"/v1/attendance/sessions/{sid}/adjustments", headers=supervisor(), json={"requested_start": start.isoformat(), "requested_end": (start + timedelta(hours=9)).isoformat(),
                                                                                                  "reason": "ran over"}).status_code == 422  # approved: reopen first
    assert client.post(f"/v1/attendance/sessions/{sid}/reopen", json={"reason": "short"}, headers=supervisor()).status_code == 422
    r = client.post(f"/v1/attendance/sessions/{sid}/reopen", json={"reason": "payroll queried the break"}, headers=supervisor())
    assert r.status_code == 200 and r.json() == {"session_id": sid, "approval": "pending", "revision": 2}
    assert client.post(f"/v1/attendance/sessions/{sid}/reopen", json={"reason": "again for no reason"}, headers=supervisor()).status_code == 422
    client.post(f"/v1/attendance/sessions/{sid}/approve", headers=supervisor())
    h = client.get(f"/v1/attendance/sessions/{sid}/history", headers=supervisor()).json()
    assert [(v["revision"], v["action"]) for v in h["revisions"]] == [(1, "approved"), (1, "reopened"), (2, "approved")]
    assert h["revisions"][1]["snapshot"]["payable_minutes"] == 450 and h["revisions"][1]["reason"] == "payroll queried the break"
    assert client.post(f"/v1/attendance/sessions/{sid}/reopen", json={"reason": "an analyst may not"}, headers=context_header(roles=["analyst"], user_id="usr_an")).status_code == 403


def test_missing_session_request_creates_evidence_only_on_approval(client, kit):
    start = datetime.now(UTC) - timedelta(hours=30)
    body = {"worker_id": "wrk_b", "start_at": start.isoformat(), "end_at": (start + timedelta(hours=8)).isoformat(), "break_minutes": 30, "reason": "kiosk was offline all shift"}
    r = client.post(f"/v1/sites/{SITE}/attendance/missing-session", json=body, headers=supervisor())
    assert r.status_code == 201, r.text
    with client.session_local() as s:
        assert s.scalars(select(AttendanceSession)).all() == []
    q = client.get(f"/v1/sites/{SITE}/attendance/corrections", headers=supervisor()).json()
    assert [(c["kind"], c["state"]) for c in q] == [("add_missing", "pending")]
    assert client.post(f"/v1/attendance/adjustments/{r.json()['id']}/approve", json={}, headers=manager()).status_code == 200
    with client.session_local() as s:
        x = s.scalars(select(AttendanceSession)).one()
        pk = s.scalars(select(AttendancePunch).where(AttendancePunch.session_id == x.id).order_by(AttendancePunch.at)).all()
    assert x.worker_id == "wrk_b" and x.state == "closed" and [p.source for p in pk] == ["correction", "correction"]
    assert client.post(f"/v1/sites/{SITE}/attendance/missing-session", json=body, headers=supervisor()).status_code == 422  # now overlaps real attendance
    assert client.post(f"/v1/sites/{SITE}/attendance/missing-session", json={**body, "worker_id": "nobody"}, headers=supervisor()).status_code == 404
    assert client.post(f"/v1/sites/{SITE}/attendance/missing-session", json={**body, "start_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
                                                                              "end_at": (datetime.now(UTC) + timedelta(hours=5)).isoformat()}, headers=supervisor()).status_code == 400


def test_approve_many_reports_what_it_could_not_approve(client, kit):
    ok, _ = _session(client, hours_ago=40)
    open_id = core(client, "clock_in", worker="wrk_b")[1]
    r = client.post("/v1/attendance/sessions/approve-many", json={"session_ids": [ok, open_id, "ghost"]}, headers=supervisor())
    assert r.status_code == 200 and r.json()["approved"] == [ok]
    assert {x["session_id"] for x in r.json()["skipped"]} == {open_id, "ghost"}
    again = client.post("/v1/attendance/sessions/approve-many", json={"session_ids": [ok]}, headers=supervisor()).json()
    assert again["approved"] == [] and again["skipped"][0]["reason"] == "already approved"


# ---------------------------------------------------------------- payroll export
def test_payroll_export_has_only_approved_hours_and_says_what_it_left_out(client, kit):
    t = datetime.now(UTC) - timedelta(days=1)
    a = seed_closed(client, "wrk_a", t, t + timedelta(hours=8), brk=30)
    seed_closed(client, "wrk_b", t, t + timedelta(hours=6))  # not approved
    with client.session_local() as s:
        s.get(WorkerPerson, "wrk_a").display_name = "=cmd|' /C calc'!A0"
        s.commit()
    client.post(f"/v1/attendance/sessions/{a}/approve", headers=supervisor())
    start = (t - timedelta(days=2)).date().isoformat()
    r = client.get(f"/v1/sites/{SITE}/exports/payroll-timesheets.csv", params={"start": start, "days": 7}, headers=manager())
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "payroll-timesheets" in r.headers["content-disposition"]
    lines = [ln for ln in r.text.splitlines() if not ln.startswith('"# ') and not ln.startswith("# ")]
    assert lines[0].startswith("employee_no,worker_id,name,work_date") and len(lines) == 2
    assert "1001" in lines[1] and "wrk_b" not in r.text.split("employee_no")[1]
    assert "'=cmd" in r.text  # spreadsheet formula neutralised
    assert "1 session(s) in this period are not yet approved and are NOT included" in r.text
    assert "Hours only: no award or pay interpretation" in r.text
    assert "7.5" in lines[1]  # 8h less a 30 minute unpaid break
    assert client.get(f"/v1/sites/{SITE}/exports/payroll-timesheets.csv", headers=context_header(roles=["analyst"], user_id="usr_an")).status_code == 403
    assert client.get(f"/v1/sites/{SITE}/exports/payroll-timesheets.csv", headers=context_header(roles=["planner"], user_id="usr_pl")).status_code == 403  # export but not attendance approval
    assert client.get(f"/v1/sites/{SITE}/exports/timesheets.csv", params={"start": start}, headers=manager()).status_code == 200  # the existing report export is unaffected


# ---------------------------------------------------------------- badge / PIN administration
def test_credential_roster_never_exposes_pins_and_a_reset_clears_the_lock(client, kit):
    for _ in range(6):
        tap(client, kit, "clock-in", pin="9999")
    roster = {r["worker_id"]: r for r in client.get(f"/v1/sites/{SITE}/clock-credentials", headers=admin()).json()}
    assert roster["wrk_a"]["has_pin"] is True and roster["wrk_a"]["locked"] is True and roster["wrk_a"]["badge_no"] == "1001" and "pin_hash" not in roster["wrk_a"]
    assert "argon2" not in client.get(f"/v1/sites/{SITE}/clock-credentials", headers=admin()).text
    assert tap(client, kit, "clock-in").status_code == 403  # locked, even with the right PIN
    assert client.get(f"/v1/sites/{SITE}/clock-credentials", headers=supervisor()).status_code == 403
    assert client.post("/v1/attendance/credentials", json={"worker_id": "wrk_a", "pin": "12"}, headers=admin()).status_code == 422  # 4 to 8 digits
    assert client.post("/v1/attendance/credentials", json={"worker_id": "wrk_a", "pin": "246810"}, headers=admin()).status_code == 201
    assert tap(client, kit, "clock-in", pin="246810").status_code == 200  # reset also cleared the lockout
    assert client.post("/v1/workers/wrk_b/clock-credential/unlock", headers=admin()).json() == {"worker_id": "wrk_b", "locked": False}


# ---------------------------------------------------------------- concurrency and device state
def test_simultaneous_clock_ins_make_exactly_one_session(client, kit):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    gate = Barrier(4)

    def go(_):
        gate.wait()
        return tap(client, kit, "clock-in")

    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(go, range(4)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]   # losers are told it is already recorded, not given an error
    assert sorted(r.json()["duplicate"] for r in results) == [False, True, True, True]
    assert len({r.json()["attendance_session_id"] for r in results}) == 1
    with client.session_local() as s:
        assert len(s.scalars(select(AttendanceSession)).all()) == 1 and len(s.scalars(select(AttendancePunch)).all()) == 1


def test_a_disabled_kiosk_cannot_record_anything_and_nothing_is_half_recorded(client, kit):
    assert tap(client, kit, "clock-in").status_code == 200
    dev = client.get("/v1/devices", headers=admin()).json()[0]["device_id"]
    assert client.post(f"/v1/devices/{dev}/disable", headers=admin()).status_code == 200
    for path in ("clock-out", "break-start", "clock-in"):
        assert tap(client, kit, path).status_code == 401
    with client.session_local() as s:
        assert [p.kind for p in s.scalars(select(AttendancePunch))] == ["clock_in"]


# ---------------------------------------------------------------- location and the site fence
MEL = {"latitude": -37.8136, "longitude": 144.9631}


def _rules(client, mode, fence=True):
    if fence:
        assert client.put(f"/v1/sites/{SITE}/geofence", json={**MEL, "radius_meters": 200}, headers=admin()).status_code == 200
    body = {"breaks_paid": False, "rounding_minutes": 0, "rounding_mode": "nearest", "duplicate_window_seconds": 30, "late_grace_minutes": 5,
            "missing_punch_after_hours": 14, "excessive_hours": 12, "location_mode": mode}
    return client.put(f"/v1/sites/{SITE}/attendance-policy", json=body, headers=admin())


def _tap_at(client, kit, path, gps, worker="wrk_a"):
    return client.post(f"/v1/attendance/{path}", json={"method": "pin", "worker_id": worker, "pin": "1234", "gps": gps}, headers=kit)


def test_fence_is_set_by_a_configurer_and_location_cannot_be_turned_on_without_one(client, kit):
    assert client.get(f"/v1/sites/{SITE}/geofence", headers=supervisor()).json()["configured"] is False
    assert _rules(client, "record", fence=False).status_code == 400
    assert client.put(f"/v1/sites/{SITE}/geofence", json={**MEL, "radius_meters": 200}, headers=supervisor()).status_code == 403
    assert client.put(f"/v1/sites/{SITE}/geofence", json={**MEL, "radius_meters": 5}, headers=admin()).status_code == 422
    assert _rules(client, "record").status_code == 200
    assert client.get(f"/v1/sites/{SITE}/geofence", headers=supervisor()).json()["radius_meters"] == 200
    who = client.post("/v1/attendance/whoami", json={"method": "pin", "worker_id": "wrk_a", "pin": "1234"}, headers=kit).json()
    assert who["location_mode"] == "record"


def test_record_mode_keeps_every_punch_and_stores_where_the_kiosk_was(client, kit):
    _rules(client, "record")
    near = {**MEL, "accuracy_m": 12}
    far = {"latitude": -38.0, "longitude": 145.5, "accuracy_m": 30}
    assert _tap_at(client, kit, "clock-in", near).status_code == 200
    assert _tap_at(client, kit, "break-start", far).status_code == 200      # outside is flagged, never blocked, in record mode
    assert _tap_at(client, kit, "break-end", {"error": "denied"}).status_code == 200
    assert _tap_at(client, kit, "clock-out", None).status_code == 200
    with client.session_local() as s:
        ps = s.scalars(select(AttendancePunch).order_by(AttendancePunch.at, AttendancePunch.id)).all()
    assert [p.location_status for p in ps] == ["passed", "outside", "denied", "unavailable"]
    assert ps[0].distance_m < 5 and ps[0].accuracy_m == 12 and ps[1].distance_m > 1000 and ps[2].latitude is None
    r = client.get(f"/v1/sites/{SITE}/attendance/daily", headers=supervisor()).json()["rows"]
    flags = next(x for x in r if x["worker_id"] == "wrk_a")["flags"]
    assert "outside_site" in flags and "no_location" in flags
    sid = next(x for x in r if x["worker_id"] == "wrk_a")["session_id"]
    h = client.get(f"/v1/attendance/sessions/{sid}/history", headers=supervisor()).json()["punches"]
    assert h[1]["location_status"] == "outside" and h[1]["distance_m"] > 1000


def test_require_mode_refuses_outside_or_missing_location_and_records_nothing(client, kit):
    _rules(client, "require")
    far = {"latitude": -38.0, "longitude": 145.5}
    r = _tap_at(client, kit, "clock-in", far)
    assert r.status_code == 422 and "not recorded" in r.json()["detail"]
    assert _tap_at(client, kit, "clock-in", None).status_code == 422
    assert _tap_at(client, kit, "clock-in", {"error": "denied"}).status_code == 422
    with client.session_local() as s:
        assert s.scalars(select(AttendancePunch)).all() == [] and s.scalars(select(AttendanceSession)).all() == []
    ok = _tap_at(client, kit, "clock-in", MEL)
    assert ok.status_code == 200 and ok.json()["geofence_status"] == "passed"
    assert _tap_at(client, kit, "clock-out", far).status_code == 422                      # leaving also needs to be at the site
    with client.session_local() as s:
        assert [p.kind for p in s.scalars(select(AttendancePunch))] == ["clock_in"]
    # a repeat tap is still answered from the first punch when the position is good
    assert _tap_at(client, kit, "clock-in", MEL).json()["duplicate"] is True


def test_location_off_does_not_ask_or_store(client, kit):
    assert _tap_at(client, kit, "clock-in", MEL).status_code == 200
    with client.session_local() as s:
        p = s.scalars(select(AttendancePunch)).one()
    assert p.location_status == "not_requested" and p.latitude is None
