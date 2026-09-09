"""Intraday Labour Reallocation (Min-Cost Flow) — AI Labour Optimisation
Spec §3.5 / Appendix A.5.

A genuinely different solver family from workforce_mix/training_coverage/
leave_rdo (all MILP): this is a bipartite worker->zone assignment network
solved with OR-Tools' SimpleMinCostFlow, not a general-purpose MILP solver.

Network (all costs scaled to integer cents, `MONEY_SCALE`):
- worker_i -> zone_z, capacity 1, cost = move_cost(i,z) - risk_per_unit *
  productivity(i,z) — moving (or staying, at zero move cost for a
  worker's current zone) nets against the backlog-risk avoided by
  covering one unit there.
- zone_z -> SINK (real), capacity = backlog units in that zone, cost 0 —
  the benefit was already priced on the incoming arc.
- zone_z -> SINK (overflow), capacity = worker count (generous upper
  bound), cost = +risk_per_unit — backlog left uncovered still costs the
  risk; assigning more workers than a zone's backlog needs nets to just
  the move cost (reward and penalty cancel), so surplus workers land on
  their zero-cost current zone rather than moving pointlessly.
- Every worker supplies exactly 1 unit of flow; SINK demands the total —
  always balanced and always feasible (the overflow arcs guarantee a
  destination for every unit of supply), matching this codebase's
  "always feasible via a penalized slack" pattern in the MILP solvers.

Processes a single current interval (`planning_window.start` for
`planning_window.bucket_minutes`), not the whole window — "intraday" means
right now, and this would be called again for the next interval, not
asked to plan a whole week upfront like the other models.

Scope reductions:
- **Live backlog has no real source yet** — `ZoneBacklog` is a new
  canonical table (this model's only consumer so far), populated by
  direct insert/seed until a WMS connector exists (tracked in
  docs/roadmap.md), the same bootstrap this codebase already used for
  `DemandBucket` ahead of Phase A.
- **Productivity is fixed at 1.0** — same simplification as
  `workforce_mix`; no per-worker-per-zone productivity data modelled.
- **Move cost is flat** regardless of which two zones are involved — no
  real zone-to-zone distance/cost matrix exists yet.
- **`cap_i` (available labour minutes) isn't modelled separately** — each
  active worker contributes exactly one assignment for the interval;
  partial-capacity splits aren't represented.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ortools.graph.python import min_cost_flow
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.policy import resolve_policy
from app.models.canonical import ActivityRoleZoneMap, ShiftAssignment, SkillCertification, Worker, ZoneBacklog
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome

MONEY_SCALE = 100  # dollars -> cents, for the flow's integer arc costs


def _active_workers_with_current_zone(db: Session, tenant_id: str, site_id: str, interval_start: datetime, interval_end: datetime) -> dict[str, str]:
    rows = db.scalars(
        select(ShiftAssignment)
        .join(Worker, Worker.worker_id == ShiftAssignment.worker_id)
        .where(ShiftAssignment.tenant_id == tenant_id)
        .where(Worker.home_site == site_id)
        .where(ShiftAssignment.start_at <= interval_start)
        .where(ShiftAssignment.end_at > interval_start)
    ).all()
    current_zone: dict[str, str] = {}
    for row in rows:
        current_zone.setdefault(row.worker_id, row.zone)
    return current_zone


def _eligible_zones(db: Session, tenant_id: str, site_id: str, window_end: datetime) -> dict[str, set[str]]:
    """Zones each worker could be moved to, via their certified role's
    ActivityRoleZoneMap entries (the worker's current zone is always
    additionally eligible — added by the caller).
    """
    skill_rows = db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == tenant_id)).all()
    worker_skills: dict[str, set[str]] = defaultdict(set)
    for row in skill_rows:
        valid_to = row.valid_to
        if valid_to is not None and valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        if valid_to is None or valid_to >= window_end:
            worker_skills[row.worker_id].add(row.skill_code)

    map_rows = db.scalars(
        select(ActivityRoleZoneMap).where(ActivityRoleZoneMap.tenant_id == tenant_id).where(ActivityRoleZoneMap.site_id == site_id)
    ).all()
    zones_by_role: dict[str, set[str]] = defaultdict(set)
    for row in map_rows:
        zones_by_role[row.role].add(row.zone)

    eligible: dict[str, set[str]] = defaultdict(set)
    for worker_id, skills in worker_skills.items():
        for skill in skills:
            eligible[worker_id] |= zones_by_role.get(skill, set())
    return eligible


def solve_intraday_reallocation(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    site_id = site_ids[0]
    policy = resolve_policy(db, tenant_id, request.configuration.policy_version)
    move_cost = policy.constraints["intraday_move_cost"]
    risk_per_unit = policy.constraints["intraday_backlog_risk_per_unit"]
    productivity = 1.0

    interval_start = request.planning_window.start
    interval_end = interval_start + timedelta(minutes=request.planning_window.bucket_minutes)

    backlog_rows = db.scalars(
        select(ZoneBacklog)
        .where(ZoneBacklog.tenant_id == tenant_id)
        .where(ZoneBacklog.site_id == site_id)
        .where(ZoneBacklog.interval_start == interval_start)
    ).all()
    if not backlog_rows:
        raise InsufficientData(f"no zone_backlog rows for tenant '{tenant_id}' at interval {interval_start.isoformat()}")
    backlog_by_zone = {row.zone: row.backlog_units for row in backlog_rows}

    current_zone = _active_workers_with_current_zone(db, tenant_id, site_id, interval_start, interval_end)
    if not current_zone:
        raise InsufficientData(f"no active ShiftAssignment covers interval {interval_start.isoformat()} at site '{site_id}'")
    eligible_extra = _eligible_zones(db, tenant_id, site_id, request.planning_window.end)

    workers = sorted(current_zone.keys())
    zones = sorted(set(backlog_by_zone) | set(current_zone.values()))
    worker_index = {worker_id: i for i, worker_id in enumerate(workers)}
    zone_index = {zone: len(workers) + i for i, zone in enumerate(zones)}
    sink = len(workers) + len(zones)

    mcf = min_cost_flow.SimpleMinCostFlow()
    assignment_arcs: dict[int, tuple[str, str]] = {}
    for worker_id in workers:
        worker_zones = {current_zone[worker_id]} | eligible_extra.get(worker_id, set())
        for zone in worker_zones:
            cost = round(MONEY_SCALE * ((0.0 if zone == current_zone[worker_id] else move_cost) - risk_per_unit * productivity))
            arc = mcf.add_arc_with_capacity_and_unit_cost(worker_index[worker_id], zone_index[zone], 1, cost)
            assignment_arcs[arc] = (worker_id, zone)
        mcf.set_node_supply(worker_index[worker_id], 1)

    overflow_arcs: dict[int, str] = {}
    real_arcs: dict[int, str] = {}
    for zone in zones:
        backlog = backlog_by_zone.get(zone, 0.0)
        real_arc = mcf.add_arc_with_capacity_and_unit_cost(zone_index[zone], sink, max(0, round(backlog)), 0)
        real_arcs[real_arc] = zone
        overflow_arc = mcf.add_arc_with_capacity_and_unit_cost(zone_index[zone], sink, len(workers), round(MONEY_SCALE * risk_per_unit))
        overflow_arcs[overflow_arc] = zone

    mcf.set_node_supply(sink, -len(workers))

    status = mcf.solve()
    if status != mcf.OPTIMAL:
        raise InsufficientData("intraday reallocation min-cost flow did not return an optimal solution")

    reassignments = []
    moved_count = 0
    for arc, (worker_id, zone) in assignment_arcs.items():
        if mcf.flow(arc) != 1:
            continue
        moved = zone != current_zone[worker_id]
        moved_count += int(moved)
        reassignments.append({"worker_id": worker_id, "from_zone": current_zone[worker_id], "to_zone": zone, "moved": moved})

    uncovered_by_zone = {zone: mcf.flow(arc) for arc, zone in overflow_arcs.items()}
    total_backlog = sum(backlog_by_zone.values())
    total_uncovered = sum(uncovered_by_zone.values())
    coverage_pct = round(100 * max(0.0, 1 - total_uncovered / total_backlog), 2) if total_backlog else 100.0

    # Baseline: nobody moves — each zone is covered only by workers already there.
    baseline_uncovered = 0.0
    for zone in zones:
        already_there = sum(1 for z in current_zone.values() if z == zone)
        baseline_uncovered += max(0.0, backlog_by_zone.get(zone, 0.0) - already_there)

    return SolverOutcome(
        result={
            "reassignments": reassignments,
            "kpis": {
                "coverage_pct": coverage_pct,
                "remaining_backlog": round(total_uncovered, 2),
                "workers_moved": moved_count,
            },
        },
        baseline={"method": "no_reallocation", "remaining_backlog": round(baseline_uncovered, 2)},
        proposed={"method": "min_cost_flow_reallocation", "remaining_backlog": round(total_uncovered, 2)},
        delta={"remaining_backlog": round(total_uncovered - baseline_uncovered, 2)},
        dollar_value=None,
        confidence_components=ConfidenceComponents(
            completeness=1.0,
            freshness=1.0,
            mapping_quality=round(len(eligible_extra) / len(workers), 4) if workers else 0.0,
            forecast_validation=1.0,
            constraint_coverage=1.0 if total_uncovered == 0 else 0.6,
            solution_quality=1.0,
        ),
        primary_drivers=[
            f"Min-cost flow over {len(workers)} active workers x {len(zones)} zones; {moved_count} reassigned"
        ]
        + ([f"{round(total_uncovered, 1)} backlog units remain uncovered — insufficient eligible workers"] if total_uncovered > 0 else []),
        missing_evidence=[],
        assumptions=[
            f"policy '{policy.policy_version}': move cost ${move_cost}, backlog risk ${risk_per_unit}/unit",
            "productivity fixed at 1.0 for every worker/zone",
            "processes a single current interval, not the full planning window",
        ],
        feasibility="feasible_with_slack" if total_uncovered > 0 else "feasible",
    )
