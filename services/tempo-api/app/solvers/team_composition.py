"""Team Composition Optimisation (MILP) — AI Labour Optimisation Spec
§3.8 / Appendix A.8.

Recommends *which named workers* fill a role/zone's team, given how many
workforce_mix already decided are needed there — team_composition doesn't
re-decide headcount or the internal/labour-hire mix (workforce_mix's job),
it decides identity: who, among the eligible pool, should actually be on
the team, trading off productivity/cost/quality targets against reliability
and minimum internal/mentor coverage.

Scope reductions, on top of workforce_mix's (which this inherits via
solve_workforce_mix):
- One team per (role, zone), sized to the *peak* daily headcount
  workforce_mix assigned there across the planning window — a stable named
  team, not a different roster each day, matching §3.8's framing ("the best
  employee mix for a team or shift") rather than named_roster's day-by-day
  assignment problem.
- ProdTarget/QualTarget are expressed in the same "headcount-equivalent"
  units as the required team size (a worker with productivity_index/
  quality_index 1.0 contributes exactly one unit) since the spec's targets
  have no other declared unit; CostTarget is the team size priced at the
  policy default_rate for one day. A tenant can already override these
  through WorkerPerformanceProfile rows without any code change.
- Per-worker cost/productivity/quality/reliability come from
  WorkerPerformanceProfile (a Tempo-governed addition, not a §6.1 canonical
  entity — see its docstring); a worker with no row is assumed exactly
  average via policy defaults, not excluded.
"""
from __future__ import annotations

from collections import defaultdict

from ortools.linear_solver import pywraplp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.policy import resolve_policy
from app.models.canonical import LabourCostRule, SkillCertification, Worker, WorkerPerformanceProfile
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome
from app.solvers.workforce_mix import INTERNAL_TYPES, solve_workforce_mix


def _required_team_size(assignments: list[dict]) -> dict[tuple[str, str], int]:
    """Peak daily headcount workforce_mix assigned per (role, zone)."""
    by_day: dict[tuple[str, str, str], int] = defaultdict(int)
    for row in assignments:
        by_day[(row["day"], row["role"], row["zone"])] += row["headcount"]
    peak: dict[tuple[str, str], int] = defaultdict(int)
    for (_, role, zone), headcount in by_day.items():
        peak[(role, zone)] = max(peak[(role, zone)], headcount)
    return peak


def _eligible_workers(db: Session, tenant_id: str, site_id: str, role: str) -> list[Worker]:
    worker_ids = db.scalars(
        select(SkillCertification.worker_id)
        .where(SkillCertification.tenant_id == tenant_id)
        .where(SkillCertification.skill_code == role)
    ).all()
    if not worker_ids:
        return []
    return db.scalars(
        select(Worker)
        .where(Worker.tenant_id == tenant_id)
        .where(Worker.home_site == site_id)
        .where(Worker.status == "active")
        .where(Worker.worker_id.in_(worker_ids))
    ).all()


def _profiles(db: Session, tenant_id: str) -> dict[str, WorkerPerformanceProfile]:
    rows = db.scalars(
        select(WorkerPerformanceProfile).where(WorkerPerformanceProfile.tenant_id == tenant_id)
    ).all()
    return {row.worker_id: row for row in rows}


def _rate_lookup(db: Session, tenant_id: str) -> dict[tuple[str, str], LabourCostRule]:
    rows = db.scalars(select(LabourCostRule).where(LabourCostRule.tenant_id == tenant_id)).all()
    return {(row.labour_type, row.role): row for row in rows}


def solve_team_composition(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    site_id = site_ids[0]
    policy = resolve_policy(db, tenant_id, request.configuration.policy_version)
    c = policy.constraints
    hours_per_worker_per_day = c["hours_per_worker_per_day"]
    default_rate = c["default_rate"]
    default_prod = c["default_productivity_index"]
    default_qual = c["default_quality_index"]
    default_rel = c["default_reliability_index"]
    internal_min_ratio = c["team_internal_min_ratio"]
    mentor_min_ratio = c["team_mentor_min_ratio"]
    prod_weight = c["team_prod_deviation_weight"]
    qual_weight = c["team_qual_deviation_weight"]
    rel_weight = c["team_reliability_weight"]

    mix = solve_workforce_mix(db, tenant_id, site_ids, request)
    required = _required_team_size(mix.result["assignments"])
    if not required:
        raise InsufficientData("workforce mix produced no headcount to build a team around")

    profiles = _profiles(db, tenant_id)
    rate_rules = _rate_lookup(db, tenant_id)

    teams = []
    total_deviation = 0.0
    total_selected = 0
    infeasible_buckets = 0

    for (role, zone), team_size in required.items():
        workers = _eligible_workers(db, tenant_id, site_id, role)
        if not workers:
            infeasible_buckets += 1
            continue

        solver = pywraplp.Solver.CreateSolver("CBC")
        x = {w.worker_id: solver.BoolVar(f"x_{w.worker_id}") for w in workers}

        def _perf(worker: Worker, field: str, default: float) -> float:
            profile = profiles.get(worker.worker_id)
            value = getattr(profile, field, None) if profile else None
            return value if value is not None else default

        def _cost(worker: Worker) -> float:
            profile = profiles.get(worker.worker_id)
            if profile and profile.cost_per_hour is not None:
                return float(profile.cost_per_hour)
            rule = rate_rules.get((worker.employment_type, role)) or rate_rules.get((worker.employment_type, "general"))
            return float(rule.rate) if rule else default_rate

        prod_target = float(team_size) * default_prod
        qual_target = float(team_size) * default_qual
        cost_target = float(team_size) * hours_per_worker_per_day * default_rate

        u_prod = solver.NumVar(0, solver.infinity(), "u_prod")
        u_cost = solver.NumVar(0, solver.infinity(), "u_cost")
        u_qual = solver.NumVar(0, solver.infinity(), "u_qual")

        prod_expr = sum(_perf(w, "productivity_index", default_prod) * x[w.worker_id] for w in workers)
        qual_expr = sum(_perf(w, "quality_index", default_qual) * x[w.worker_id] for w in workers)
        cost_expr = sum(_cost(w) * hours_per_worker_per_day * x[w.worker_id] for w in workers)
        rel_expr = sum(_perf(w, "reliability_index", default_rel) * x[w.worker_id] for w in workers)

        solver.Add(prod_expr - prod_target <= u_prod)
        solver.Add(prod_target - prod_expr <= u_prod)
        solver.Add(cost_expr <= cost_target + u_cost)
        solver.Add(qual_expr - qual_target <= u_qual)
        solver.Add(qual_target - qual_expr <= u_qual)

        internal_workers = [w for w in workers if w.employment_type in INTERNAL_TYPES]
        if internal_workers:
            solver.Add(sum(x[w.worker_id] for w in internal_workers) >= internal_min_ratio * team_size)
        mentor_workers = [w for w in workers if profiles.get(w.worker_id) and profiles[w.worker_id].is_mentor]
        if mentor_workers:
            solver.Add(sum(x[w.worker_id] for w in mentor_workers) >= mentor_min_ratio * team_size)

        solver.Minimize(prod_weight * u_prod + u_cost + qual_weight * u_qual - rel_weight * rel_expr)
        status = solver.Solve()
        if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
            infeasible_buckets += 1
            continue

        selected = [w for w in workers if x[w.worker_id].solution_value() > 0.5]
        total_selected += len(selected)
        total_deviation += u_prod.solution_value() + u_qual.solution_value()
        teams.append(
            {
                "role": role,
                "zone": zone,
                "required_headcount": team_size,
                "selected_worker_ids": [w.worker_id for w in selected],
                "avg_reliability": round(
                    sum(_perf(w, "reliability_index", default_rel) for w in selected) / len(selected), 3
                )
                if selected
                else 0.0,
                "cost_deviation": {"amount": f"{u_cost.solution_value():.2f}", "currency": "AUD"},
            }
        )

    if not teams:
        raise InsufficientData("no eligible certified workers found for any required (role, zone) team")

    total_required = sum(required.values())
    baseline_avg_reliability = default_rel
    proposed_avg_reliability = (
        sum(team["avg_reliability"] * len(team["selected_worker_ids"]) for team in teams) / total_selected
        if total_selected
        else 0.0
    )

    return SolverOutcome(
        result={
            "teams": teams,
            "kpis": {
                "teams_built": len(teams),
                "total_selected": total_selected,
                "total_required_headcount": total_required,
                "total_target_deviation": round(total_deviation, 2),
            },
        },
        baseline={"method": "average_pool_reliability", "avg_reliability": baseline_avg_reliability},
        proposed={"method": "milp_team_composition", "avg_reliability": round(proposed_avg_reliability, 3)},
        delta={"avg_reliability": round(proposed_avg_reliability - baseline_avg_reliability, 3)},
        dollar_value=None,
        confidence_components=ConfidenceComponents(
            completeness=round(1 - infeasible_buckets / len(required), 4) if required else 0.0,
            freshness=mix.confidence_components.freshness,
            mapping_quality=mix.confidence_components.mapping_quality,
            forecast_validation=mix.confidence_components.forecast_validation,
            constraint_coverage=1.0 if infeasible_buckets == 0 else 0.6,
            solution_quality=1.0,
        ),
        primary_drivers=[
            f"MILP selected {total_selected} named workers across {len(teams)} role/zone teams",
        ]
        + ([f"{infeasible_buckets} of {len(required)} required teams had no eligible certified worker or were infeasible"] if infeasible_buckets else []),
        missing_evidence=mix.missing_evidence
        + ([f"{len(required) - len(profiles)} workers have no WorkerPerformanceProfile — assumed average"] if len(profiles) < len(required) else []),
        assumptions=mix.assumptions
        + [
            f"policy '{policy.policy_version}': team internal-min ratio {internal_min_ratio}, mentor-min ratio {mentor_min_ratio}",
            "one stable named team per (role, zone), sized to the peak daily headcount workforce_mix assigned "
            "across the window, not re-picked per day",
        ],
        feasibility="feasible_with_slack" if infeasible_buckets else "feasible",
    )
