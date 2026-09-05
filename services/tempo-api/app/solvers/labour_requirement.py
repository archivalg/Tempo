"""Labour Requirement and Work Content — AI Labour Optimisation Spec §3.2 / Appendix A.2.

HoursReq_(a,t,w) = V_(a,t,w) x TimePerUnit_(a,e,z,w), aggregated to
role/zone via beta_(a,r,z,w) (ActivityRoleZoneMap). Falls back to a flat
default time-per-unit or an even activity->role/zone split when the
governed configuration for either is missing, and always says so in
missing_evidence rather than silently defaulting (Integration Spec §2.3's
"never silently degrade" rule, applied here to Tempo's own configuration
gaps, not just third-party source gaps).
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import ActivityRoleZoneMap, WorkStandard
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import SolverOutcome
from app.solvers.demand_forecast import forecast_demand

DEFAULT_TIME_PER_UNIT_SECONDS = 60.0
DEFAULT_ROLE, DEFAULT_ZONE = "general", "general"


def _day_bucket(iso_timestamp: str) -> str:
    return iso_timestamp[:10]


def _work_standard_lookup(db: Session, tenant_id: str) -> dict[str, float]:
    rows = db.scalars(select(WorkStandard).where(WorkStandard.tenant_id == tenant_id)).all()
    # Latest effective_from wins per activity — Phase A doesn't yet resolve
    # complexity segments or effective-date windows against the planning day.
    by_activity: dict[str, WorkStandard] = {}
    for row in rows:
        current = by_activity.get(row.activity)
        if current is None or row.effective_from > current.effective_from:
            by_activity[row.activity] = row
    return {activity: row.time_per_unit_seconds for activity, row in by_activity.items()}


def _role_zone_map(db: Session, tenant_id: str, site_id: str) -> dict[str, list[tuple[str, str, float]]]:
    rows = db.scalars(
        select(ActivityRoleZoneMap)
        .where(ActivityRoleZoneMap.tenant_id == tenant_id)
        .where(ActivityRoleZoneMap.site_id == site_id)
    ).all()
    mapping: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for row in rows:
        mapping[row.activity].append((row.role, row.zone, row.weight))
    return mapping


def translate_labour_requirement(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    site_id = site_ids[0]
    forecast_outcome = forecast_demand(db, tenant_id, site_ids, request)
    forecast_rows = forecast_outcome.result["forecast"]

    volume_by_activity_day: dict[tuple[str, str], float] = defaultdict(float)
    for row in forecast_rows:
        volume_by_activity_day[(row["activity"], _day_bucket(row["bucket_start"]))] += row["point"]

    time_per_unit = _work_standard_lookup(db, tenant_id)
    role_zone_map = _role_zone_map(db, tenant_id, site_id)

    activities = {activity for activity, _ in volume_by_activity_day}
    activities_with_standard = activities & time_per_unit.keys()
    activities_with_mapping = activities & role_zone_map.keys()

    hours_default: dict[tuple[str, str, str], float] = defaultdict(float)  # baseline: flat default everywhere
    hours_governed: dict[tuple[str, str, str], float] = defaultdict(float)  # proposed: real config where available

    for (activity, day), volume in volume_by_activity_day.items():
        seconds_per_unit = time_per_unit.get(activity, DEFAULT_TIME_PER_UNIT_SECONDS)
        governed_hours = volume * seconds_per_unit / 3600
        default_hours = volume * DEFAULT_TIME_PER_UNIT_SECONDS / 3600

        targets = role_zone_map.get(activity) or [(DEFAULT_ROLE, DEFAULT_ZONE, 1.0)]
        weight_total = sum(w for _, _, w in targets) or 1.0
        for role, zone, weight in targets:
            share = weight / weight_total
            hours_governed[(day, role, zone)] += governed_hours * share
            hours_default[(day, role, zone)] += default_hours * share

    result_rows = [
        {"day": day, "role": role, "zone": zone, "hours": round(hours, 3)}
        for (day, role, zone), hours in sorted(hours_governed.items())
    ]

    missing_evidence = list(forecast_outcome.missing_evidence)
    if activities - activities_with_standard:
        missing_evidence.append(
            f"{len(activities - activities_with_standard)} of {len(activities)} activities have no WorkStandard "
            f"configured; used a default {DEFAULT_TIME_PER_UNIT_SECONDS:.0f}s/unit"
        )
    if activities - activities_with_mapping:
        missing_evidence.append(
            f"{len(activities - activities_with_mapping)} of {len(activities)} activities have no "
            f"ActivityRoleZoneMap configured; assigned to a single '{DEFAULT_ROLE}/{DEFAULT_ZONE}' bucket"
        )

    total_governed = sum(hours_governed.values())
    total_default = sum(hours_default.values())

    return SolverOutcome(
        result={"hours_requirement": result_rows, "kpis": {"total_hours": round(total_governed, 2)}},
        baseline={"method": "flat_default_time_per_unit", "total_hours": round(total_default, 2)},
        proposed={"method": "governed_work_standards", "total_hours": round(total_governed, 2)},
        delta={"total_hours": round(total_governed - total_default, 2)},
        confidence_components=ConfidenceComponents(
            completeness=round(len(activities_with_standard) / len(activities), 4) if activities else 0.0,
            freshness=forecast_outcome.confidence_components.freshness,
            mapping_quality=round(len(activities_with_mapping) / len(activities), 4) if activities else 0.0,
            forecast_validation=forecast_outcome.confidence_components.forecast_validation,
            constraint_coverage=1.0,
            solution_quality=1.0,
        ),
        primary_drivers=[f"Translated demand for {len(activities)} activities across {len(result_rows)} day/role/zone buckets"],
        missing_evidence=missing_evidence,
        assumptions=forecast_outcome.assumptions
        + [f"missing WorkStandard/ActivityRoleZoneMap falls back to {DEFAULT_TIME_PER_UNIT_SECONDS:.0f}s/unit and an even split"],
        feasibility="feasible",
    )
