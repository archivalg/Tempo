"""Order-driven-planning Stage 1 acceptance: calendars, shift templates, breaks (docs/order-driven-planning.md).

v1 import contracts (workers/sites/etc.) are untouched; these are new v1.1-additive master entities.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.models.canonical import ActivityRoleZoneMap
from app.models.directory import Zone
from app.models.scheduling import OperatingCalendarDay, ShiftBreak, ShiftTemplate
from app.solvers.shifts import BreakDefinition, shift_elapsed_minutes, shift_hours

from .test_imports import MEL, admin, csv_text, seed, stage


def apply(client, h, b):
    r = client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------------------------- zones / activity roles
def test_zones_and_activity_roles_round_trip_without_duplicating_on_replay(client):
    seed(client)
    h = admin()
    f = csv_text(["site", "zone_id", "zone_name"], [[MEL, "PICK", "Picking"], [MEL, "PACK", "Packing"]])
    b = apply(client, h, stage(client, h, "master", f, entity="zones").json())
    assert b["summary"]["applied"] == {"created": 2, "updated": 0}
    again = apply(client, h, stage(client, h, "master", f, entity="zones").json())
    assert again["state"] == "applied" and again["id"] == b["id"]  # replayed, not duplicated
    with client.session_local() as s:
        assert s.scalar(select(Zone.zone_id).where(Zone.tenant_id == "ten_test", Zone.site_id == MEL, Zone.zone_id == "PICK")) == "PICK"

    f2 = csv_text(["site", "activity", "role", "zone_id", "weight"], [[MEL, "picking", "picker", "PICK", "1.0"]])
    ar = apply(client, h, stage(client, h, "master", f2, entity="activity_roles").json())
    assert ar["summary"]["applied"] == {"created": 1, "updated": 0}
    with client.session_local() as s:
        m = s.scalar(select(ActivityRoleZoneMap).where(ActivityRoleZoneMap.tenant_id == "ten_test", ActivityRoleZoneMap.activity == "picking"))
        assert m.role == "picker" and m.zone == "PICK" and m.weight == 1.0

    bad = csv_text(["site", "activity", "role", "zone_id", "weight"], [[MEL, "picking", "picker", "NOPE", "1.0"]])
    rejected = stage(client, h, "master", bad, entity="activity_roles").json()
    assert rejected["error_rows"] == 1
    with client.session_local() as s:
        from app.models.imports import ImportRow
        row = s.scalar(select(ImportRow).where(ImportRow.batch_id == rejected["id"]))
        assert any("not set up" in m["text"] for m in row.messages)


# --------------------------------------------------------------------------------------------- operating calendar
def test_operating_calendar_requires_24h_closed_or_both_times(client):
    seed(client)
    h = admin()
    ambiguous = csv_text(["site", "weekday", "is_24h", "is_closed", "open_time", "close_time"], [[MEL, "monday", "false", "false", "09:00", "09:00"]])
    r = stage(client, h, "master", ambiguous, entity="operating_calendar").json()
    assert r["error_rows"] == 1

    both = csv_text(["site", "weekday", "is_24h", "is_closed", "open_time", "close_time"], [[MEL, "monday", "true", "true", "", ""]])
    r2 = stage(client, h, "master", both, entity="operating_calendar").json()
    assert r2["error_rows"] == 1

    ok = csv_text(["site", "weekday", "is_24h", "is_closed", "open_time", "close_time"], [[MEL, "monday", "false", "false", "06:00", "23:00"], [MEL, "tuesday", "true", "false", "", ""]])
    done = apply(client, h, stage(client, h, "master", ok, entity="operating_calendar").json())
    assert done["summary"]["applied"] == {"created": 2, "updated": 0}
    with client.session_local() as s:
        mon = s.scalar(select(OperatingCalendarDay).where(OperatingCalendarDay.tenant_id == "ten_test", OperatingCalendarDay.site_id == MEL, OperatingCalendarDay.weekday == "monday"))
        assert mon.open_time == "06:00" and mon.close_time == "23:00" and not mon.is_24h
        tue = s.scalar(select(OperatingCalendarDay).where(OperatingCalendarDay.tenant_id == "ten_test", OperatingCalendarDay.site_id == MEL, OperatingCalendarDay.weekday == "tuesday"))
        assert tue.is_24h and tue.open_time is None


# --------------------------------------------------------------------------------------------- shift templates + conflict warning
def test_shift_template_outside_operating_hours_warns_but_is_not_silently_changed(client):
    seed(client)
    h = admin()
    cal = csv_text(["site", "weekday", "is_24h", "is_closed", "open_time", "close_time"], [[MEL, "monday", "false", "false", "06:00", "14:00"]])
    apply(client, h, stage(client, h, "master", cal, entity="operating_calendar").json())

    shift = csv_text(["site", "shift_code", "start_time", "end_time", "weekdays"], [[MEL, "late", "12:00", "20:00", "monday"]])
    staged = stage(client, h, "master", shift, entity="shift_templates").json()
    assert staged["warning_rows"] == 1 and staged["error_rows"] == 0  # flagged, not blocked
    done = apply(client, h, staged)
    assert done["summary"]["applied"]["created"] == 1
    with client.session_local() as s:
        t = s.scalar(select(ShiftTemplate).where(ShiftTemplate.tenant_id == "ten_test", ShiftTemplate.site_id == MEL, ShiftTemplate.shift_code == "late"))
        assert t.start_time == "12:00" and t.end_time == "20:00"  # stored exactly as supplied, not altered


def test_shift_template_versions_on_change_and_rejects_unknown_weekday(client):
    seed(client)
    h = admin()
    bad = csv_text(["site", "shift_code", "start_time", "end_time", "weekdays"], [[MEL, "morning", "06:00", "14:00", "funday"]])
    assert stage(client, h, "master", bad, entity="shift_templates").json()["error_rows"] == 1

    f1 = csv_text(["site", "shift_code", "start_time", "end_time", "weekdays", "effective_from"],
                  [[MEL, "morning", "06:00", "14:00", "monday;tuesday;wednesday;thursday;friday", "2026-01-01"]])
    apply(client, h, stage(client, h, "master", f1, entity="shift_templates").json())
    f2 = csv_text(["site", "shift_code", "start_time", "end_time", "weekdays", "effective_from"],
                  [[MEL, "morning", "07:00", "15:00", "monday;tuesday;wednesday;thursday;friday", "2026-06-01"]])
    apply(client, h, stage(client, h, "master", f2, entity="shift_templates").json())
    with client.session_local() as s:
        rows = list(s.scalars(select(ShiftTemplate).where(ShiftTemplate.tenant_id == "ten_test", ShiftTemplate.site_id == MEL, ShiftTemplate.shift_code == "morning")))
        assert len(rows) == 2
        closed = next(r for r in rows if r.effective_to is not None)
        current = next(r for r in rows if r.effective_to is None)
        assert closed.start_time == "06:00" and current.start_time == "07:00" and closed.effective_to == date(2026, 6, 1)


# --------------------------------------------------------------------------------------------- shift breaks
def test_shift_break_must_fit_inside_its_shift(client):
    seed(client)
    h = admin()
    f1 = csv_text(["site", "shift_code", "start_time", "end_time", "weekdays"], [[MEL, "night", "22:00", "06:00", "monday"]])
    apply(client, h, stage(client, h, "master", f1, entity="shift_templates").json())  # 480 elapsed minutes

    too_long = csv_text(["site", "shift_code", "starts_after_minutes", "duration_minutes", "is_paid"], [[MEL, "night", "470", "30", "false"]])
    assert stage(client, h, "master", too_long, entity="shift_breaks").json()["error_rows"] == 1

    unknown = csv_text(["site", "shift_code", "starts_after_minutes", "duration_minutes", "is_paid"], [[MEL, "nope", "10", "30", "false"]])
    assert stage(client, h, "master", unknown, entity="shift_breaks").json()["error_rows"] == 1

    ok = csv_text(["site", "shift_code", "starts_after_minutes", "duration_minutes", "is_paid"],
                  [[MEL, "night", "120", "20", "true"], [MEL, "night", "240", "30", "false"]])
    done = apply(client, h, stage(client, h, "master", ok, entity="shift_breaks").json())
    assert done["summary"]["applied"]["created"] == 2
    with client.session_local() as s:
        breaks = list(s.scalars(select(ShiftBreak).where(ShiftBreak.tenant_id == "ten_test")))
        assert len(breaks) == 2 and {b.is_paid for b in breaks} == {True, False}


# --------------------------------------------------------------------------------------------- paid vs productive hours (brief Appendix C)
def test_overnight_shift_paid_and_productive_hours_ordinary_night():
    """22:00-06:00 with a 30-min unpaid break and a 20-min paid break: 7.5 paid hours, 7h10m productive."""
    elapsed = shift_elapsed_minutes("22:00", "06:00")
    assert elapsed == 480  # 8 hours
    breaks = [BreakDefinition(starts_after_minutes=120, duration_minutes=20, is_paid=True), BreakDefinition(starts_after_minutes=240, duration_minutes=30, is_paid=False)]
    hours = shift_hours(elapsed, breaks)
    assert hours["elapsed_hours"] == pytest.approx(8.0)
    assert hours["paid_hours"] == pytest.approx(7.5)
    assert hours["productive_hours"] == pytest.approx(7 + 10 / 60)


def test_equal_start_end_time_is_a_full_24_hour_shift_not_zero():
    assert shift_elapsed_minutes("06:00", "06:00") == 1440
