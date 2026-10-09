"""Order-driven-planning Stage 3 acceptance scenarios (docs/order-driven-planning.md):
fill priorities, absenteeism, equipment pools, headcount limits.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.constraints import AbsenteeismRule as AbsenteeismRuleModel
from app.models.constraints import Equipment as EquipmentModel
from app.models.constraints import FillPriority, HeadcountLimit
from app.solvers.constraints import (
    AbsenteeismRule,
    AmbiguousAbsenteeismRule,
    EquipmentAssignment,
    InvalidHeadcountLimit,
    check_equipment_capacity,
    check_headcount_limit,
    fill_priority_key,
    resolve_absenteeism,
    scheduled_hours_for_absenteeism,
)

from .test_imports import MEL, admin, csv_text, seed, stage


def apply(client, h, b):
    r = client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------------------------- absenteeism
def test_ten_percent_absence_needs_eleven_percent_extra_scheduled_hours():
    assert scheduled_hours_for_absenteeism(9, 0.10) == pytest.approx(10.0)
    with pytest.raises(ValueError):
        scheduled_hours_for_absenteeism(9, 1.0)


def test_absenteeism_resolves_most_specific_rule_and_rejects_ties():
    rules = [
        AbsenteeismRule(site_id="mel", activity=None, weekday=None, shift_code=None, absence_pct=0.05),
        AbsenteeismRule(site_id="mel", activity="picking", weekday=None, shift_code=None, absence_pct=0.10),
    ]
    r = resolve_absenteeism(rules, site_id="mel", activity="picking", weekday="monday", shift_code="morning")
    assert r.absence_pct == 0.10  # more specific (activity-scoped) wins over the site-wide default

    tied = rules + [AbsenteeismRule(site_id="mel", activity=None, weekday="monday", shift_code=None, absence_pct=0.20)]
    # "picking" rule (specificity 1) vs "monday" rule (specificity 1): both match picking-on-monday equally specifically
    with pytest.raises(AmbiguousAbsenteeismRule):
        resolve_absenteeism(tied, site_id="mel", activity="picking", weekday="monday", shift_code="morning")


def test_absenteeism_import_round_trip(client):
    seed(client)
    h = admin()
    f = csv_text(["site", "activity", "absence_pct"], [[MEL, "picking", "10"]])
    done = apply(client, h, stage(client, h, "master", f, entity="absenteeism").json())
    assert done["summary"]["applied"] == {"created": 1, "updated": 0}
    with client.session_local() as s:
        r = s.scalar(select(AbsenteeismRuleModel).where(AbsenteeismRuleModel.tenant_id == "ten_test", AbsenteeismRuleModel.site_id == MEL))
        assert r.absence_pct == pytest.approx(0.10) and r.weekday is None


# --------------------------------------------------------------------------------------------- equipment
def test_three_high_reach_trucks_block_a_fourth_simultaneous_assignment_including_overlapping_shifts():
    base = datetime(2026, 10, 12, 6, 0, tzinfo=timezone.utc)
    assignments = [
        EquipmentAssignment("a1", "HIGH_REACH", base, base + timedelta(hours=8)),
        EquipmentAssignment("a2", "HIGH_REACH", base, base + timedelta(hours=8)),
        EquipmentAssignment("a3", "HIGH_REACH", base + timedelta(hours=4), base + timedelta(hours=12)),  # overlapping shift, not the same one
        EquipmentAssignment("a4", "HIGH_REACH", base + timedelta(hours=5), base + timedelta(hours=13)),  # the fourth concurrent user
    ]
    violations = check_equipment_capacity(assignments, pools={"HIGH_REACH": 3})
    assert violations
    assert all(v.equipment_id == "HIGH_REACH" and v.concurrent == 4 for v in violations)

    ok = check_equipment_capacity(assignments[:3], pools={"HIGH_REACH": 3})
    assert ok == []


def test_equipment_import_round_trip(client):
    seed(client)
    h = admin()
    f = csv_text(["site", "equipment_id", "description", "quantity_available"], [[MEL, "HIGH_REACH", "High-reach forklift", "3"]])
    done = apply(client, h, stage(client, h, "master", f, entity="equipment").json())
    assert done["summary"]["applied"] == {"created": 1, "updated": 0}
    with client.session_local() as s:
        e = s.scalar(select(EquipmentModel).where(EquipmentModel.tenant_id == "ten_test", EquipmentModel.site_id == MEL, EquipmentModel.equipment_id == "HIGH_REACH"))
        assert e.quantity_available == 3


# --------------------------------------------------------------------------------------------- headcount limits
def test_headcount_limit_detects_min_above_max():
    with pytest.raises(InvalidHeadcountLimit):
        check_headcount_limit(assigned=2, min_headcount=5, max_headcount=3)
    assert check_headcount_limit(assigned=2, min_headcount=1, max_headcount=5) is None
    assert "below minimum" in check_headcount_limit(assigned=0, min_headcount=1, max_headcount=5)
    assert "exceeds maximum" in check_headcount_limit(assigned=6, min_headcount=1, max_headcount=5)


def test_headcount_limit_import_rejects_min_above_max(client):
    seed(client)
    h = admin()
    bad = csv_text(["site", "activity", "min_headcount", "max_headcount"], [[MEL, "picking", "5", "3"]])
    assert stage(client, h, "master", bad, entity="headcount_limits").json()["error_rows"] == 1

    ok = csv_text(["site", "activity", "min_headcount", "max_headcount"], [[MEL, "picking", "1", "6"]])
    done = apply(client, h, stage(client, h, "master", ok, entity="headcount_limits").json())
    assert done["summary"]["applied"] == {"created": 1, "updated": 0}
    with client.session_local() as s:
        h2 = s.scalar(select(HeadcountLimit).where(HeadcountLimit.tenant_id == "ten_test", HeadcountLimit.site_id == MEL, HeadcountLimit.activity == "picking"))
        assert h2.min_headcount == 1 and h2.max_headcount == 6


# --------------------------------------------------------------------------------------------- fill priorities
def test_fill_priority_lower_first_ties_equal_unconfigured_falls_back():
    priorities = {("activity", "picking"): 1, ("activity", "packing"): 1, ("activity", "dispatch"): 2}
    ranked = sorted(["dispatch", "packing", "picking", "returns"], key=lambda a: fill_priority_key(priorities, scope="activity", value=a))
    assert ranked == ["packing", "picking", "dispatch", "returns"] or ranked == ["picking", "packing", "dispatch", "returns"]  # ties keep stable relative order
    assert fill_priority_key(priorities, scope="activity", value="packing") == fill_priority_key(priorities, scope="activity", value="picking")
    assert fill_priority_key(priorities, scope="activity", value="returns") == 999  # unconfigured never jumps the queue


def test_fill_priority_import_round_trip(client):
    seed(client)
    h = admin()
    f = csv_text(["scope", "value", "priority"], [["activity", "picking", "1"], ["activity", "packing", "1"]])
    done = apply(client, h, stage(client, h, "master", f, entity="fill_priorities").json())
    assert done["summary"]["applied"] == {"created": 2, "updated": 0}
    with client.session_local() as s:
        rows = {(p.scope, p.value): p.priority for p in s.scalars(select(FillPriority).where(FillPriority.tenant_id == "ten_test"))}
        assert rows[("activity", "picking")] == rows[("activity", "packing")] == 1  # equal priority, never inferred as ranked
