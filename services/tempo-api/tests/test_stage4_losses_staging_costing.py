"""Order-driven-planning Stage 4 acceptance scenarios (docs/order-driven-planning.md):
staging capacity, costing (paid vs unpaid breaks, grade/provider rates), congestion/off-task loss.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.canonical import LabourCostRule
from app.models.stage4 import StagingCapacity as StagingCapacityModel
from app.solvers.losses import (
    CostRule,
    StagingMovement,
    StagingUnitMismatch,
    apply_congestion,
    apply_off_task_hours,
    check_staging_capacity,
    compute_staging_occupancy,
    labour_cost,
    resolve_cost_rate,
)
from app.solvers.shifts import BreakDefinition, shift_hours

from .test_imports import MEL, admin, csv_text, seed, stage


def apply(client, h, b):
    r = client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------------------------- staging capacity
def test_staging_occupancy_110_plus_20_minus_5_violates_120_cap():
    t0 = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
    movements = [
        StagingMovement(t0, "initial", 110, "pallets"),
        StagingMovement(t0.replace(hour=6), "arrival", 20, "pallets"),
        StagingMovement(t0.replace(hour=8), "departure", 5, "pallets"),
    ]
    points = compute_staging_occupancy(movements, capacity_unit="pallets")
    assert points[-1].occupancy == pytest.approx(125.0)  # 110 + 20 - 5 = 125, over the 120 cap
    violations = check_staging_capacity(points, capacity=120)
    assert violations and violations[-1].occupancy == pytest.approx(125.0)  # every instant over cap is flagged, including the final one


def test_staging_unit_mismatch_prevents_claiming_validated_capacity():
    t0 = datetime(2026, 10, 12, 0, 0, tzinfo=timezone.utc)
    movements = [StagingMovement(t0, "initial", 110, "pallets"), StagingMovement(t0, "arrival", 20, "cases")]
    with pytest.raises(StagingUnitMismatch):
        compute_staging_occupancy(movements, capacity_unit="pallets")


def test_staging_import_requires_matching_unit_and_existing_zone(client):
    seed(client)
    h = admin()
    zones = csv_text(["site", "zone_id", "zone_name"], [[MEL, "STAGE", "Staging"]])
    apply(client, h, stage(client, h, "master", zones, entity="zones").json())

    cap = csv_text(["site", "zone_id", "capacity", "unit"], [[MEL, "STAGE", "120", "pallets"]])
    done = apply(client, h, stage(client, h, "master", cap, entity="staging_capacity").json())
    assert done["summary"]["applied"] == {"created": 1, "updated": 0}

    mismatched = csv_text(["site", "zone_id", "occurred_at", "movement_type", "quantity", "unit"], [[MEL, "STAGE", "2026-10-12 06:00", "arrival", "20", "cases"]])
    assert stage(client, h, "master", mismatched, entity="staging_movements").json()["error_rows"] == 1

    ok = csv_text(["site", "zone_id", "occurred_at", "movement_type", "quantity", "unit"],
                  [[MEL, "STAGE", "2026-10-12 00:00", "initial", "110", "pallets"], [MEL, "STAGE", "2026-10-12 06:00", "arrival", "20", "pallets"], [MEL, "STAGE", "2026-10-12 08:00", "departure", "5", "pallets"]])
    done2 = apply(client, h, stage(client, h, "master", ok, entity="staging_movements").json())
    assert done2["summary"]["applied"]["created"] == 3
    with client.session_local() as s:
        c = s.scalar(select(StagingCapacityModel).where(StagingCapacityModel.tenant_id == "ten_test", StagingCapacityModel.site_id == MEL, StagingCapacityModel.zone_id == "STAGE"))
        assert c.capacity == 120


# --------------------------------------------------------------------------------------------- costing: paid vs unpaid breaks
def test_paid_breaks_incur_cost_unpaid_breaks_do_not():
    elapsed = 480  # 8-hour shift
    breaks = [BreakDefinition(starts_after_minutes=120, duration_minutes=20, is_paid=True), BreakDefinition(starts_after_minutes=240, duration_minutes=30, is_paid=False)]
    hours = shift_hours(elapsed, breaks)
    cost = labour_cost(paid_hours=hours["paid_hours"], rate_per_hour=40)
    # 7.5 paid hours includes the 20-minute paid break; the 30-minute unpaid break was never in paid_hours.
    assert cost == pytest.approx(7.5 * 40)
    productive_only_cost = labour_cost(paid_hours=hours["productive_hours"], rate_per_hour=40)
    assert cost > productive_only_cost  # the paid break's cost is the difference


# --------------------------------------------------------------------------------------------- costing: grade/provider rates
def test_grade_and_provider_rate_precedence_and_missing_rate_is_none_not_zero():
    rules = [
        CostRule(labour_type="labour_hire", role="picker", rate=40.0),
        CostRule(labour_type="labour_hire", role="picker", rate=48.0, position_grade="senior"),
        CostRule(labour_type="labour_hire", role="picker", rate=52.0, position_grade="senior", provider_id="prov_A"),
    ]
    general = resolve_cost_rate(rules, labour_type="labour_hire", role="picker")
    assert general.rate == 40.0 and not general.matched_grade
    grade_only = resolve_cost_rate(rules, labour_type="labour_hire", role="picker", position_grade="senior")
    assert grade_only.rate == 48.0 and grade_only.matched_grade
    grade_and_provider = resolve_cost_rate(rules, labour_type="labour_hire", role="picker", position_grade="senior", provider_id="prov_A")
    assert grade_and_provider.rate == 52.0 and grade_and_provider.matched_provider
    assert resolve_cost_rate(rules, labour_type="permanent", role="supervisor") is None  # no invented rate — caller must show cost as unavailable


def test_grade_rate_import_and_resolution_against_db(client):
    seed(client)
    h = admin()
    general = csv_text(["employment_type", "role", "hourly_rate"], [["labour_hire", "picker", "40"]])
    apply(client, h, stage(client, h, "master", general, entity="rates").json())
    grade = csv_text(["employment_type", "role", "position_grade", "hourly_rate"], [["labour_hire", "picker", "senior", "48"]])
    done = apply(client, h, stage(client, h, "master", grade, entity="grade_rates").json())
    assert done["summary"]["applied"]["created"] == 1
    with client.session_local() as s:
        rows = [CostRule(labour_type=c.labour_type, role=c.role, rate=float(c.rate), position_grade=c.position_grade, provider_id=c.provider_id)
                for c in s.scalars(select(LabourCostRule).where(LabourCostRule.tenant_id == "ten_test"))]
    assert resolve_cost_rate(rows, labour_type="labour_hire", role="picker").rate == 40.0
    assert resolve_cost_rate(rows, labour_type="labour_hire", role="picker", position_grade="senior").rate == 48.0


# --------------------------------------------------------------------------------------------- congestion / off-task
def test_congestion_reduces_rate_off_task_reduces_hours_explicitly_no_double_deduction():
    reduced_rate = apply_congestion(100, 0.10)
    assert reduced_rate == pytest.approx(90.0)
    reduced_hours = apply_off_task_hours(8.0, 0.5)
    assert reduced_hours == pytest.approx(7.5)
    with pytest.raises(ValueError):
        apply_congestion(100, 1.0)


def test_productivity_loss_import_requires_exactly_one_of_percent_or_hours(client):
    seed(client)
    h = admin()
    both = csv_text(["site", "type", "percent_loss", "off_task_hours"], [[MEL, "congestion", "10", "0.5"]])
    assert stage(client, h, "master", both, entity="productivity_loss").json()["error_rows"] == 1
    neither = csv_text(["site", "type"], [[MEL, "off_task"]])
    assert stage(client, h, "master", neither, entity="productivity_loss").json()["error_rows"] == 1
    ok = csv_text(["site", "type", "percent_loss"], [[MEL, "congestion", "10"]])
    done = apply(client, h, stage(client, h, "master", ok, entity="productivity_loss").json())
    assert done["summary"]["applied"] == {"created": 1, "updated": 0}
