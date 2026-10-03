"""Kiosk (tablet) operation: QR identification from the employee app, manager-authorised exit, revocation, server-side sequence validation; DST and overnight display."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.config import settings
from app.core import passwords
from app.models.attendance import AttendancePunch
from app.models.canonical import AttendanceSession, ShiftAssignment
from app.models.identity import SecurityAuditEvent

from .conftest import context_header, enrol_kiosk
from .test_mobile import ADMIN, SITE, add_committed, employee_login, seed_people, MEL, UTC, run_jobs
from .test_password_login import PW, mkuser


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    from app.core.password_login import throttle
    throttle.reset()


def qr(client, h):
    r = client.post("/v1/me/kiosk-qr", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def tap(client, kiosk, path, token):
    return client.post(f"/v1/attendance/{path}", json={"method": "qr", "qr_token": token}, headers=kiosk)


def test_qr_identification_clocks_a_full_cycle_and_each_code_works_once(client):
    seed_people(client)
    kiosk = enrol_kiosk(client)
    h, _ = employee_login(client, "wrk_emp")
    t = qr(client, h)
    who = client.post("/v1/attendance/whoami", json={"method": "qr", "qr_token": t}, headers=kiosk)                # the preview does not spend the code
    assert who.status_code == 200 and who.json()["state"] == "not_clocked_in" and who.json()["allowed_actions"] == ["clock_in"]
    assert client.post("/v1/attendance/whoami", json={"method": "qr", "qr_token": t}, headers=kiosk).status_code == 200
    first = tap(client, kiosk, "clock-in", t)
    assert first.status_code == 200 and first.json()["state"] == "working"
    assert tap(client, kiosk, "clock-in", t).status_code == 401                                   # the same code cannot be replayed
    for path, state in (("break-start", "on_break"), ("break-end", "working"), ("clock-out", "closed")):
        r = tap(client, kiosk, path, qr(client, h))
        assert r.status_code == 200 and (r.json().get("state") == state), (path, r.text)
    with client.session_local() as s:
        assert [p.kind for p in s.scalars(select(AttendancePunch).order_by(AttendancePunch.at, AttendancePunch.id))] == ["clock_in", "break_start", "break_end", "clock_out"]
    # invalid sequences are refused by the server, whatever the app shows
    assert tap(client, kiosk, "break-start", qr(client, h)).status_code == 409                    # not clocked in
    assert tap(client, kiosk, "break-end", qr(client, h)).status_code == 409                      # not on a break
    again = tap(client, kiosk, "clock-out", qr(client, h))                                        # an immediate repeat of the last action is a harmless duplicate, not a second record
    assert again.status_code == 200 and again.json()["duplicate"] is True


def test_a_qr_code_is_useless_when_forged_expired_or_used_at_another_companys_kiosk(client, monkeypatch):
    seed_people(client)
    kiosk = enrol_kiosk(client)
    h, _ = employee_login(client, "wrk_emp")
    t = qr(client, h)
    nonce, sig = t[4:].split(".")
    assert tap(client, kiosk, "clock-in", f"tqr_{nonce}.{'0' * 32}").status_code == 401           # forged signature
    assert tap(client, kiosk, "clock-in", "tqr_nope.abc").status_code == 401 and tap(client, kiosk, "clock-in", "garbage").status_code == 401
    other = enrol_kiosk(client, tenant_id="ten_other", site_ids=("o_site",))
    assert tap(client, other, "clock-in", t).status_code == 401                                    # another company's kiosk cannot redeem it
    assert tap(client, kiosk, "clock-in", t).status_code == 200                                    # and the real kiosk still can (the failed attempts did not spend it)
    monkeypatch.setattr(settings, "kiosk_qr_ttl_seconds", -5)
    assert tap(client, kiosk, "clock-out", qr(client, h)).status_code == 401                       # expired on arrival
    from app.models.mobile import KioskQrNonce
    with client.session_local() as s:
        assert all(n.used_at is None or n.worker_id == "wrk_emp" for n in s.scalars(select(KioskQrNonce)))


def test_a_revoked_device_and_an_unlinked_employee_cannot_clock(client):
    seed_people(client)
    kiosk = enrol_kiosk(client)
    h, _ = employee_login(client, "wrk_emp")
    dev = client.get("/v1/devices", headers=ADMIN()).json()[0]["device_id"]
    assert client.post(f"/v1/devices/{dev}/disable", headers=ADMIN()).status_code == 200
    assert tap(client, kiosk, "clock-in", qr(client, h)).status_code == 401                        # revoked: nothing is recorded
    with client.session_local() as s:
        assert s.scalars(select(AttendancePunch)).all() == []
    assert client.get("/v1/devices", headers=ADMIN()).json()[0]["status"] == "disabled"


def test_leaving_kiosk_mode_needs_a_manager_for_this_device(client):
    seed_people(client)
    kiosk = enrol_kiosk(client)
    employee_login(client, "wrk_emp")
    mkuser(client, email="boss@example.test", username="boss", roles=("tenant_admin",), totp=passwords.new_totp_secret())
    secret = passwords.new_totp_secret()
    mkuser(client, email="boss2@example.test", username="boss2", roles=("tenant_admin",), totp=secret)
    mkuser(client, email="ops@example.test", username="opsmgr", roles=("operations_manager",))
    body = {"username": "x", "password": "y"}
    assert client.post("/v1/kiosk/exit-authorise", json=body).status_code == 401                              # a kiosk credential is required
    assert client.post("/v1/kiosk/exit-authorise", json={"username": "emp1", "password": "Correct-Horse-Battery-9!"}, headers=kiosk).status_code == 403   # an employee is not a manager
    assert client.post("/v1/kiosk/exit-authorise", json={"username": "boss2", "password": "wrong"}, headers=kiosk).status_code == 401
    assert client.post("/v1/kiosk/exit-authorise", json={"username": "opsmgr", "password": PW}, headers=kiosk).status_code == 403       # not allowed to configure
    step1 = client.post("/v1/kiosk/exit-authorise", json={"username": "boss2", "password": PW}, headers=kiosk).json()
    assert step1["authorised"] is False and step1["mfa_required"] is True
    bad = client.post("/v1/kiosk/exit-authorise", json={"username": "boss2", "password": PW, "challenge": step1["challenge"], "code": "000000"}, headers=kiosk)
    assert bad.status_code == 401
    ok = client.post("/v1/kiosk/exit-authorise", json={"username": "boss2", "password": PW, "challenge": step1["challenge"], "code": passwords.totp_now(secret), "purpose": "reconfigure", "revoke_device": True}, headers=kiosk)
    assert ok.status_code == 200 and ok.json() == {"authorised": True, "purpose": "reconfigure", "device_revoked": True}
    assert client.get("/v1/devices", headers=ADMIN()).json()[0]["status"] == "disabled"                       # revocation done as part of leaving
    with client.session_local() as s:
        acts = [(e.action, e.decision) for e in s.scalars(select(SecurityAuditEvent).where(SecurityAuditEvent.action.like("kiosk.%")).order_by(SecurityAuditEvent.created_at))]
    assert ("kiosk.exit_authorise", "denied") in acts and ("kiosk.reconfigure_authorised", "allowed") in acts


def test_enrolment_records_the_platform_and_managers_see_it(client):
    seed_people(client)
    r = client.post("/v1/devices", json={"name": "Dock iPad", "site_ids": [SITE]}, headers=ADMIN())
    code = r.json()["enrolment_code"]
    e = client.post("/v1/kiosk/enrol", json={"enrolment_code": code, "platform": "ios", "app_version": "1.0.0"})
    assert e.status_code == 200
    d = client.get("/v1/devices", headers=ADMIN()).json()[0]
    assert d["client_info"] == {"platform": "ios", "app_version": "1.0.0"} and d["status"] == "active"
    assert client.post("/v1/kiosk/enrol", json={"enrolment_code": "x" * 12 + ".y", "platform": "palm"}).status_code == 422


# ------------------------------------------------------------------------------------------------ overnight and daylight saving (Melbourne clocks go forward at 02:00 on 4 Oct 2026)
def test_overnight_and_daylight_saving_shifts_are_displayed_and_reminded_correctly(client):
    seed_people(client)
    h, _ = employee_login(client, "wrk_emp")
    start = datetime(2026, 10, 3, 22, 0, tzinfo=MEL).astimezone(UTC)           # 22:00 Saturday, ends 06:00 Sunday after the clocks jump
    end = datetime(2026, 10, 4, 6, 0, tzinfo=MEL).astimezone(UTC)
    with client.session_local() as s:
        sh = ShiftAssignment(tenant_id="ten_test", worker_id="wrk_emp", role="picker", zone="z", start_at=start, end_at=end, status="committed")
        s.add(sh)
        s.commit()
        sid = sh.shift_id
    v = client.get(f"/v1/me/shifts/{sid}", headers=h).json()
    assert v["overnight"] is True and v["dst_change_during_shift"] is True
    assert v["duration_minutes"] == 7 * 60                                                                      # eight clock hours, seven real ones
    assert v["start_local"].startswith("2026-10-03T22:00:00+10:00") and v["end_local"].startswith("2026-10-04T06:00:00+11:00")
    assert v["local_date"] == "2026-10-03"
    # an ordinary night shift in winter time is 8 hours with no DST flag
    w0 = datetime(2026, 7, 3, 22, 0, tzinfo=MEL).astimezone(UTC)
    s2 = add_committed(client, "wrk_emp", w0)
    n = client.get(f"/v1/me/shifts/{s2}", headers=h).json()
    assert n["overnight"] is True and n["dst_change_during_shift"] is False and n["duration_minutes"] == 480
    # the range query is by LOCAL day: asking for Sunday 4 Oct (a 23-hour day) returns the shift that is still running
    day = client.get("/v1/me/shifts", params={"start": "2026-10-04", "end": "2026-10-04"}, headers=h).json()["shifts"]
    assert [x["id"] for x in day] == [sid]
    # reminders use the absolute start, so the clock change does not move them
    from app.core import push
    from app.models.mobile import NotificationJob
    with client.session_local() as s3:
        push.schedule_reminders(s3, "ten_test", start - timedelta(hours=2))
        s3.commit()
        job = s3.scalars(select(NotificationJob).where(NotificationJob.kind == "reminder")).one()
        assert job.run_at == start - timedelta(minutes=60)
