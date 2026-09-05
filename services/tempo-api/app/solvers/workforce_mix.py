"""Workforce Mix Optimisation (MILP) — AI Labour Optimisation Spec §3.3 / Appendix A.3.

Solved with OR-Tools' CBC MILP backend. Scope reductions from the full
formal model, each an explicit Phase A simplification tracked in
docs/roadmap.md rather than a silent gap:

- Availability A_(e,r,z) is a static headcount pool for the whole planning
  window (day-by-day absence is Named Roster's job, not Workforce Mix's).
- Role eligibility comes from SkillCertification.skill_code doubling as a
  role name; workers with no matching skill count toward the 'general' role
  bucket used when no ActivityRoleZoneMap is configured.
- Productivity/performance multipliers (p, alpha in the spec) are fixed at
  1.0 — no per-worker productivity data is modeled yet.
- Error cost (c_err) is not modeled; SLA penalty (c_sla) is a fixed
  per-hour rate applied to unmet demand.
"""
from __future__ import annotations

from collections import defaultdict

from ortools.linear_solver import pywraplp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import LabourCostRule, SkillCertification, Worker
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome
from app.solvers.labour_requirement import translate_labour_requirement

HOURS_PER_WORKER_PER_DAY = 8.0
MAX_OVERTIME_HOURS_PER_WORKER_PER_DAY = 2.0
DEFAULT_INTERNAL_MIN_RATIO = 0.6
DEFAULT_HIRE_MAX_RATIO = 0.4
DEFAULT_RATE = 40.0
DEFAULT_OVERTIME_MULTIPLIER = 1.5
DEFAULT_HIRE_SURCHARGE = 8.0
SLA_PENALTY_PER_HOUR = 250.0
INTERNAL_TYPES = {"permanent", "part_time", "casual"}  # everyone except labour_hire counts as internal


def _employment_types(db: Session, tenant_id: str, site_id: str) -> list[str]:
    rows = db.scalars(
        select(Worker.employment_type)
        .where(Worker.tenant_id == tenant_id)
        .where(Worker.home_site == site_id)
        .where(Worker.status == "active")
        .distinct()
    ).all()
    return list(rows) or ["permanent"]


def _availability(db: Session, tenant_id: str, site_id: str, roles: set[str]) -> dict[tuple[str, str], int]:
    """Returns {(employment_type, role): headcount} using skill_code as role name."""
    workers = db.scalars(
        select(Worker)
        .where(Worker.tenant_id == tenant_id)
        .where(Worker.home_site == site_id)
        .where(Worker.status == "active")
    ).all()
    skills = db.scalars(
        select(SkillCertification).where(SkillCertification.tenant_id == tenant_id)
    ).all()
    worker_skills: dict[str, set[str]] = defaultdict(set)
    for skill in skills:
        worker_skills[skill.worker_id].add(skill.skill_code)

    availability: dict[tuple[str, str], int] = defaultdict(int)
    for worker in workers:
        matched_roles = worker_skills.get(worker.worker_id, set()) & roles
        if matched_roles:
            for role in matched_roles:
                availability[(worker.employment_type, role)] += 1
        elif "general" in roles:
            availability[(worker.employment_type, "general")] += 1
    return availability


def _rate_lookup(db: Session, tenant_id: str) -> dict[tuple[str, str], LabourCostRule]:
    rows = db.scalars(select(LabourCostRule).where(LabourCostRule.tenant_id == tenant_id)).all()
    return {(row.labour_type, row.role): row for row in rows}


def _rate_for(rules: dict[tuple[str, str], LabourCostRule], employment_type: str, role: str) -> LabourCostRule | None:
    return rules.get((employment_type, role)) or rules.get((employment_type, "general"))


def solve_workforce_mix(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    site_id = site_ids[0]
    labour_req = translate_labour_requirement(db, tenant_id, site_ids, request)
    hours_rows = labour_req.result["hours_requirement"]
    if not hours_rows:
        raise InsufficientData("labour requirement translation produced no buckets to optimise a mix for")

    roles = {row["role"] for row in hours_rows}
    employment_types = _employment_types(db, tenant_id, site_id)
    availability = _availability(db, tenant_id, site_id, roles)
    rate_rules = _rate_lookup(db, tenant_id)

    solver = pywraplp.Solver.CreateSolver("CBC")
    buckets = [(row["day"], row["role"], row["zone"]) for row in hours_rows]
    hours_by_bucket = {(row["day"], row["role"], row["zone"]): row["hours"] for row in hours_rows}

    x: dict[tuple[str, str, str, str], object] = {}
    o: dict[tuple[str, str, str, str], object] = {}
    u: dict[tuple[str, str, str], object] = {}
    objective_terms = []

    for day, role, zone in buckets:
        u[(day, role, zone)] = solver.NumVar(0, solver.infinity(), f"u_{day}_{role}_{zone}")
        objective_terms.append((u[(day, role, zone)], SLA_PENALTY_PER_HOUR))

        coverage_terms = []
        internal_terms = []
        hire_terms = []
        total_terms = []
        for employment_type in employment_types:
            cap = availability.get((employment_type, role), 0)
            xi = solver.IntVar(0, max(cap, 0), f"x_{day}_{employment_type}_{role}_{zone}")
            oi = solver.NumVar(0, solver.infinity(), f"o_{day}_{employment_type}_{role}_{zone}")
            x[(day, employment_type, role, zone)] = xi
            o[(day, employment_type, role, zone)] = oi
            solver.Add(oi <= MAX_OVERTIME_HOURS_PER_WORKER_PER_DAY * xi)

            rule = _rate_for(rate_rules, employment_type, role)
            rate = float(rule.rate) if rule else DEFAULT_RATE
            ot_multiplier = float(rule.overtime_multiplier) if rule and rule.overtime_multiplier else DEFAULT_OVERTIME_MULTIPLIER
            surcharge = float(rule.surcharge) if rule and rule.surcharge else (DEFAULT_HIRE_SURCHARGE if employment_type == "labour_hire" else 0.0)

            objective_terms.append((xi, rate * HOURS_PER_WORKER_PER_DAY + surcharge * HOURS_PER_WORKER_PER_DAY))
            objective_terms.append((oi, rate * ot_multiplier))

            coverage_terms.append((xi, HOURS_PER_WORKER_PER_DAY))
            coverage_terms.append((oi, 1.0))
            total_terms.append(xi)
            if employment_type in INTERNAL_TYPES:
                internal_terms.append(xi)
            if employment_type == "labour_hire":
                hire_terms.append(xi)

        required = hours_by_bucket[(day, role, zone)]
        solver.Add(
            sum(coeff * var for var, coeff in coverage_terms) + u[(day, role, zone)] >= required
        )
        if total_terms:
            solver.Add(sum(internal_terms) >= DEFAULT_INTERNAL_MIN_RATIO * sum(total_terms))
            solver.Add(sum(hire_terms) <= DEFAULT_HIRE_MAX_RATIO * sum(total_terms))

    solver.Minimize(sum(coeff * var for var, coeff in objective_terms))
    status = solver.Solve()
    feasibility = "feasible"
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise InsufficientData("workforce mix MILP did not return a usable solution")

    assignments = []
    total_labour_cost = 0.0
    for day, employment_type, role, zone in x:
        headcount = x[(day, employment_type, role, zone)].solution_value()
        overtime = o[(day, employment_type, role, zone)].solution_value()
        if headcount <= 0 and overtime <= 0:
            continue
        rule = _rate_for(rate_rules, employment_type, role)
        rate = float(rule.rate) if rule else DEFAULT_RATE
        cost = headcount * HOURS_PER_WORKER_PER_DAY * rate
        total_labour_cost += cost
        assignments.append(
            {
                "day": day,
                "employment_type": employment_type,
                "role": role,
                "zone": zone,
                "headcount": int(round(headcount)),
                "overtime_hours": round(overtime, 2),
            }
        )

    total_required = sum(hours_by_bucket.values())
    total_unmet = sum(var.solution_value() for var in u.values())
    coverage_pct = round(100 * max(0.0, 1 - total_unmet / total_required), 2) if total_required else 100.0

    labour_hire_rate = next(
        (float(rule.rate) + float(rule.surcharge or 0) for (etype, _), rule in rate_rules.items() if etype == "labour_hire"),
        DEFAULT_RATE + DEFAULT_HIRE_SURCHARGE,
    )
    naive_hire_only_cost = total_required * labour_hire_rate

    return SolverOutcome(
        result={
            "assignments": assignments,
            "kpis": {
                "labour_cost": {"amount": f"{total_labour_cost:.2f}", "currency": "AUD"},
                "coverage_pct": coverage_pct,
                "unmet_hours": round(total_unmet, 2),
            },
        },
        baseline={
            "method": "labour_hire_only",
            "labour_cost": {"amount": f"{naive_hire_only_cost:.2f}", "currency": "AUD"},
        },
        proposed={
            "method": "milp_optimised_mix",
            "labour_cost": {"amount": f"{total_labour_cost:.2f}", "currency": "AUD"},
        },
        delta={"labour_cost": {"amount": f"{total_labour_cost - naive_hire_only_cost:.2f}", "currency": "AUD"}},
        dollar_value={"amount": f"{naive_hire_only_cost - total_labour_cost:.2f}", "currency": "AUD"},
        confidence_components=ConfidenceComponents(
            completeness=labour_req.confidence_components.completeness,
            freshness=labour_req.confidence_components.freshness,
            mapping_quality=round(len(availability) / max(len(roles), 1), 4) if roles else 0.0,
            forecast_validation=labour_req.confidence_components.forecast_validation,
            constraint_coverage=1.0 if total_unmet == 0 else 0.6,
            solution_quality=1.0 if status == pywraplp.Solver.OPTIMAL else 0.7,
        ),
        primary_drivers=[
            f"CBC MILP over {len(buckets)} day/role/zone buckets and {len(employment_types)} labour source types",
        ]
        + ([f"{round(total_unmet, 1)} hours unmet demand — insufficient available headcount"] if total_unmet > 0 else []),
        missing_evidence=labour_req.missing_evidence,
        assumptions=labour_req.assumptions
        + [
            f"static availability pool for the whole window (no day-level absence)",
            f"internal-min ratio {DEFAULT_INTERNAL_MIN_RATIO}, hire-max ratio {DEFAULT_HIRE_MAX_RATIO} (policy defaults, not tenant-configured yet)",
        ],
        feasibility="feasible_with_slack" if total_unmet > 0 else "feasible",
    )
