"""Training and Certification Coverage Optimisation (MILP) — AI Labour
Optimisation Spec §3.6 / Appendix A.6.

Required coverage req_(t,s,w) is derived from Labour Requirement's hours
need (hours / hours_per_worker_per_day, converted to headcount and ceiled),
NOT from Workforce Mix's assigned headcount — that would be circular:
workforce_mix's own availability lookup already gates headcount by current
certification (workforce_mix.py's `_availability`), so its output can never
exceed today's certified supply, and comparing "have" against a number that
can never exceed "have" can never show a shortfall. Required coverage has
to come from the underlying demand, independent of who is certified today,
for this model to be able to answer "are we short."

Consistent with the rest of this codebase, `SkillCertification.skill_code`
doubling as a role name (workforce_mix.py, named_roster.py) is what lets
Labour Requirement's per-role hours become a per-skill headcount need here.

Scope reductions, on top of Labour Requirement's (which this inherits):
- trainCost/benefit/shortage-penalty (§3.6's trainCost_(i,s),
  benefit_(i,s,t,w), c_short_(t,s,w)) have no canonical cost source yet —
  flat policy defaults (app.core.policy), same class of gap as
  workforce_mix's default_rate.
- A worker is a training candidate for a skill only if they hold no valid
  certification for it anywhere in the planning window (checked at window
  end, matching named_roster's certification-validity check) — expiry
  *during* the window isn't modelled separately.
- Budget is a single tenant-wide cap (`training_budget`), not per-site or
  per-skill.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from ortools.linear_solver import pywraplp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.policy import resolve_policy
from app.models.canonical import SkillCertification, Worker
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome
from app.solvers.labour_requirement import translate_labour_requirement


def _required_coverage(hours_rows: list[dict], hours_per_worker_per_day: float) -> dict[tuple[str, str], int]:
    """req_(t,s,w) — required certified headcount per (day, skill), from
    the underlying hours need, independent of current certified supply.
    """
    required: dict[tuple[str, str], int] = defaultdict(int)
    for row in hours_rows:
        required[(row["day"], row["role"])] += math.ceil(row["hours"] / hours_per_worker_per_day)
    return required


def _currently_certified(db: Session, tenant_id: str, window_end: datetime) -> dict[str, set[str]]:
    rows = db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == tenant_id)).all()
    have: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        valid_to = row.valid_to
        if valid_to is not None and valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        if valid_to is None or valid_to >= window_end:
            have[row.worker_id].add(row.skill_code)
    return have


def solve_training_coverage(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    site_id = site_ids[0]
    policy = resolve_policy(db, tenant_id, request.configuration.policy_version)
    c = policy.constraints
    train_cost = c["training_cost_per_certification"]
    benefit_per_period = c["training_benefit_per_certification_per_period"]
    shortage_penalty = c["training_shortage_penalty_per_worker"]
    budget = c.get("training_budget")

    labour_req = translate_labour_requirement(db, tenant_id, site_ids, request)
    required = _required_coverage(labour_req.result["hours_requirement"], c["hours_per_worker_per_day"])
    if not required:
        raise InsufficientData("labour requirement translation produced no buckets to plan certification coverage against")

    workers = db.scalars(
        select(Worker).where(Worker.tenant_id == tenant_id).where(Worker.home_site == site_id).where(Worker.status == "active")
    ).all()
    if not workers:
        raise InsufficientData(f"no active workers at site '{site_id}' to plan training for")

    window_end = request.planning_window.end
    have = _currently_certified(db, tenant_id, window_end)
    skills = {skill for _, skill in required}
    periods_per_skill: dict[str, int] = defaultdict(int)
    for (_, skill), _target in required.items():
        periods_per_skill[skill] += 1

    solver = pywraplp.Solver.CreateSolver("CBC")
    x: dict[tuple[str, str], object] = {}
    for worker in workers:
        for skill in skills:
            if skill in have.get(worker.worker_id, set()):
                continue  # already certified — not a training candidate
            x[(worker.worker_id, skill)] = solver.BoolVar(f"x_{worker.worker_id}_{skill}")

    short: dict[tuple[str, str], object] = {}
    objective_terms = []
    for (day, skill), req in required.items():
        current_supply = sum(1 for w in workers if skill in have.get(w.worker_id, set()))
        candidate_vars = [var for (worker_id, s), var in x.items() if s == skill]
        short[(day, skill)] = solver.NumVar(0, solver.infinity(), f"short_{day}_{skill}")
        solver.Add(current_supply + sum(candidate_vars) + short[(day, skill)] >= req)
        objective_terms.append((short[(day, skill)], shortage_penalty))

    for (worker_id, skill), var in x.items():
        objective_terms.append((var, train_cost - benefit_per_period * periods_per_skill[skill]))

    if budget is not None:
        solver.Add(sum(train_cost * var for var in x.values()) <= budget)

    solver.Minimize(sum(coeff * var for var, coeff in objective_terms))
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise InsufficientData("training coverage MILP did not return a usable solution")

    training_plan = [
        {"worker_id": worker_id, "skill_code": skill, "cost": {"amount": f"{train_cost:.2f}", "currency": "AUD"}}
        for (worker_id, skill), var in x.items()
        if var.solution_value() > 0.5
    ]
    total_training_cost = len(training_plan) * train_cost
    total_shortfall = sum(var.solution_value() for var in short.values())
    total_required = sum(required.values())

    baseline_shortfall = sum(
        max(0, req - sum(1 for w in workers if skill in have.get(w.worker_id, set()))) for (day, skill), req in required.items()
    )
    coverage_pct = round(100 * max(0.0, 1 - total_shortfall / total_required), 2) if total_required else 100.0

    return SolverOutcome(
        result={
            "training_plan": training_plan,
            "kpis": {
                "training_cost": {"amount": f"{total_training_cost:.2f}", "currency": "AUD"},
                "coverage_pct": coverage_pct,
                "remaining_shortfall": round(total_shortfall, 2),
            },
        },
        baseline={"method": "no_training", "shortfall_count": baseline_shortfall},
        proposed={"method": "milp_training_plan", "shortfall_count": round(total_shortfall, 2)},
        delta={"shortfall_count": round(total_shortfall - baseline_shortfall, 2)},
        dollar_value=None,
        confidence_components=ConfidenceComponents(
            completeness=labour_req.confidence_components.completeness,
            freshness=labour_req.confidence_components.freshness,
            mapping_quality=labour_req.confidence_components.mapping_quality,
            forecast_validation=labour_req.confidence_components.forecast_validation,
            constraint_coverage=1.0 if total_shortfall == 0 else 0.6,
            solution_quality=1.0 if status == pywraplp.Solver.OPTIMAL else 0.7,
        ),
        primary_drivers=[
            f"MILP over {len(workers)} workers x {len(skills)} skills, {len(training_plan)} certifications recommended",
        ]
        + ([f"{round(total_shortfall, 1)} worker-periods of certification shortfall remain — insufficient training candidates or budget"] if total_shortfall > 0 else []),
        missing_evidence=labour_req.missing_evidence,
        assumptions=labour_req.assumptions
        + [
            f"policy '{policy.policy_version}': training cost ${train_cost}/certification, "
            f"shortage penalty ${shortage_penalty}/worker-period"
            + (f", budget ${budget}" if budget is not None else ", no budget cap"),
            "required coverage per skill = ceil(labour-requirement hours / hours_per_worker_per_day), "
            "independent of who is certified today",
        ],
        feasibility="feasible_with_slack" if total_shortfall > 0 else "feasible",
    )
