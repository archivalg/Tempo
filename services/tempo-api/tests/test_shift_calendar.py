"""Shift calendar is policy-configured and timezone-correct (Blueprint §1 optimisation correction, §6)."""
from __future__ import annotations

from datetime import timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.models.canonical import OptimisationPolicy, ShiftAssignment
from app.solvers.shifts import ShiftDefinition, calendar_from_constraints, shift_bounds_utc, split_headcount

from .conftest import context_header
from .test_run_endpoint import VALID_REQUEST, _headers, _seed

MEL = "Australia/Melbourne"


def test_overnight_shift_length_and_flag():
    night = ShiftDefinition("night", 22, 6)
    assert night.hours == 8 and night.overnight
    assert ShiftDefinition("day", 6, 14).hours == 8 and not ShiftDefinition("day", 6, 14).overnight


def test_local_time_is_converted_using_the_site_timezone_not_utc():
    start, end = shift_bounds_utc("2026-09-15", ShiftDefinition("early", 6, 14), MEL)
    assert start.tzinfo == timezone.utc
    assert start.isoformat() == "2026-09-14T20:00:00+00:00"  # 06:00 AEST (+10)
    assert end.astimezone(ZoneInfo(MEL)).hour == 14


def test_dst_change_is_explicit_not_silent():
    # Melbourne clocks go forward at 02:00 on 2026-10-04: the 22:00→06:00 night shift is 7 real hours.
    start, end = shift_bounds_utc("2026-10-03", ShiftDefinition("night", 22, 6), MEL)
    assert (end - start).total_seconds() == 7 * 3600
    assert ShiftDefinition("night", 22, 6).hours == 8  # nominal paid length is reported separately


def test_calendar_validation():
    assert [s.code for s in calendar_from_constraints({})] == ["day", "night"]  # documented fallback
    cal = calendar_from_constraints({"shift_calendar": [{"code": "e", "start_hour": 6, "end_hour": 14}, {"code": "n", "start_hour": 22, "end_hour": 6}]})
    assert [(s.code, s.hours) for s in cal] == [("e", 8), ("n", 8)]
    with pytest.raises(ValueError):
        calendar_from_constraints({"shift_calendar": [{"code": "a", "start_hour": 6, "end_hour": 14}, {"code": "a", "start_hour": 14, "end_hour": 22}]})
    with pytest.raises(ValueError):
        calendar_from_constraints({"shift_calendar": [{"code": "a", "start_hour": 25, "end_hour": 3}]})


def test_named_roster_uses_the_tenant_calendar_in_site_local_time(client):
    _seed(client)
    with client.session_local() as s:
        s.add(OptimisationPolicy(policy_version="three_shift_v1", tenant_id="ten_test", constraints={
            "shift_calendar": [{"code": "early", "start_hour": 6, "end_hour": 14}, {"code": "late", "start_hour": 14, "end_hour": 22},
                               {"code": "night", "start_hour": 22, "end_hour": 6}]}))
        s.commit()
    body = {**VALID_REQUEST, "configuration": {"policy_version": "three_shift_v1"}}
    r = client.post("/v1/optimisations/named_roster", json=body, headers=_headers())
    assert r.status_code == 202, r.text
    with client.session_local() as s:
        rows = s.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_test")).all()
        assert rows
        local_starts = {r_.start_at.astimezone(ZoneInfo(MEL)).hour for r_ in rows}
        assert local_starts <= {6, 14, 22} and local_starts  # never the UTC-hour artefact
        # every assignment carries the id publish will promote
    result = client.get(f"/v1/runs/{r.json()['run_id']}", headers=context_header()).json()["result"]
    assert all(a.get("shift_id") for a in result["assignments"])


def test_headcount_split_by_configured_share_and_default_even():
    even = calendar_from_constraints({})
    assert split_headcount(7, even) == {"day": 4, "night": 3}  # unchanged legacy behaviour
    cal = calendar_from_constraints({"shift_calendar": [
        {"code": "e", "start_hour": 6, "end_hour": 14, "share": 0.48}, {"code": "l", "start_hour": 14, "end_hour": 22, "share": 0.38},
        {"code": "n", "start_hour": 22, "end_hour": 6, "share": 0.14}]})
    out = split_headcount(50, cal)
    assert sum(out.values()) == 50 and out == {"e": 24, "l": 19, "n": 7}
    assert sum(split_headcount(13, cal).values()) == 13


def test_shares_must_be_complete_and_sum_to_one():
    with pytest.raises(ValueError):
        calendar_from_constraints({"shift_calendar": [{"code": "a", "start_hour": 6, "end_hour": 14, "share": 0.5}, {"code": "b", "start_hour": 14, "end_hour": 22}]})
    with pytest.raises(ValueError):
        calendar_from_constraints({"shift_calendar": [{"code": "a", "start_hour": 6, "end_hour": 14, "share": 0.5}, {"code": "b", "start_hour": 14, "end_hour": 22, "share": 0.4}]})


def test_roster_never_breaks_the_rest_rule_and_uses_site_local_days(client):
    from datetime import datetime, timedelta

    from app.models.canonical import OptimisationPolicy

    _seed(client)
    with client.session_local() as s:
        s.add(OptimisationPolicy(policy_version="rest_v1", tenant_id="ten_test", constraints={
            "min_rest_hours": 10, "shift_calendar": [{"code": "early", "start_hour": 6, "end_hour": 14}, {"code": "late", "start_hour": 14, "end_hour": 22},
                                                     {"code": "night", "start_hour": 22, "end_hour": 6}]}))
        s.commit()
    r = client.post("/v1/optimisations/named_roster", json={**VALID_REQUEST, "configuration": {"policy_version": "rest_v1"}}, headers=_headers())
    assert r.status_code == 202, r.text
    with client.session_local() as s:
        rows = s.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_test")).all()
    by_worker = {}
    for row in rows:
        by_worker.setdefault(row.worker_id, []).append(row)
    for wid, lst in by_worker.items():
        lst.sort(key=lambda x: x.start_at)
        for a, b in zip(lst, lst[1:]):
            assert (b.start_at - a.end_at) >= timedelta(hours=10), f"{wid}: {a.end_at} -> {b.start_at}"
    # days are local: no shift starts on a local date outside the requested window
    local_days = {row.start_at.astimezone(ZoneInfo(MEL)).date().isoformat() for row in rows}
    assert min(local_days) >= "2026-09-08" and max(local_days) <= "2026-09-15"
