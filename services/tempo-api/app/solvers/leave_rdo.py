"""Leave and RDO Planning Optimisation (MILP) — AI Labour Optimisation Spec
§3.7 / Appendix A.7.

Approves or rejects pending leave/RDO requests, balancing staffing-gap risk
against approval-rejection dissatisfaction. Required coverage req_(d,r,z,w)
comes from Labour Requirement's hours need (as in training_coverage.py),
not from Workforce Mix's assigned headcount — same circularity reasoning:
mix's own availability lookup already reflects who's currently expected to
work, so it can't independently tell you whether granting a request creates
a *new* gap.

A pending request is represented as an `Availability` row with status
`leave_requested` or `rdo_requested` — a new convention on top of the
`available`/`unavailable`/`leave`/`rdo` values Named Roster already reads.
This model decides `x_(i,d)` (approve); it does not write the outcome back
to `Availability` — that's Phase E (controlled action/writeback), not a
Phase C planning run.

Scope reductions, on top of Labour Requirement's (which this inherits):
- `priority_(i,d)` reuses `Availability.preference` on the request row —
  a genuine double-duty of a field Named Roster already reads for shift
  preference; there's no separate approval-priority entity yet.
- costShort/costReject (§3.7's costShort_(d,r,z,w), costReject_(i,d)) are
  flat policy defaults (app.core.policy), the same class of gap as
  workforce_mix's default_rate.
- Role eligibility again follows `SkillCertification.skill_code`
  doubling as a role name; a worker with no matching skill counts toward
  the 'general' bucket only when required coverage has one.
- No explicit fairness term distributing approvals evenly (§3.7 lists it
  as optional) — priority-weighted approval is the only equity lever here.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone

from ortools.linear_solver import pywraplp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.policy import resolve_policy
from app.models.canonical import Availability, SkillCertification, Worker
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome
from app.solvers.labour_requirement import translate_labour_requirement

REQUEST_STATUSES = {"leave_requested", "rdo_requested"}
ALREADY_UNAVAILABLE_STATUSES = {"unavailable", "leave", "rdo"}
DEFAULT_ROLE = "general"


def _required_coverage(hours_rows: list[dict], hours_per_worker_per_day: float) -> dict[tuple[str, str], int]:
    required: dict[tuple[str, str], int] = defaultdict(int)
    for row in hours_rows:
        required[(row["day"], row["role"])] += math.ceil(row["hours"] / hours_per_worker_per_day)
    return required


def _worker_skills(db: Session, tenant_id: str, window_end: datetime) -> dict[str, set[str]]:
    rows = db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == tenant_id)).all()
    skills: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        valid_to = row.valid_to
        if valid_to is not None and valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        if valid_to is None or valid_to >= window_end:
            skills[row.worker_id].add(row.skill_code)
    return skills


def _availability_rows_by_day(db: Session, tenant_id: str) -> dict[tuple[str, str], Availability]:
    rows = db.scalars(select(Availability).where(Availability.tenant_id == tenant_id)).all()
    by_worker_day: dict[tuple[str, str], Availability] = {}
    for row in rows:
        day = row.interval_start.date().isoformat()
        by_worker_day[(row.worker_id, day)] = row
    return by_worker_day


def _eligible_roles(worker_skills: set[str], required_roles: set[str]) -> set[str]:
    matched = worker_skills & required_roles
    if matched:
        return matched
    return {DEFAULT_ROLE} if DEFAULT_ROLE in required_roles else set()


def solve_leave_rdo(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    site_id = site_ids[0]
    policy = resolve_policy(db, tenant_id, request.configuration.policy_version)
    c = policy.constraints
    shortage_penalty = c["leave_shortage_penalty_per_worker"]
    rejection_penalty = c["leave_rejection_penalty"]

    labour_req = translate_labour_requirement(db, tenant_id, site_ids, request)
    required = _required_coverage(labour_req.result["hours_requirement"], c["hours_per_worker_per_day"])
    if not required:
        raise InsufficientData("labour requirement translation produced no buckets to plan leave/RDO against")
    required_roles = {role for _, role in required}
    days = sorted({day for day, _ in required})

    workers = db.scalars(
        select(Worker).where(Worker.tenant_id == tenant_id).where(Worker.home_site == site_id).where(Worker.status == "active")
    ).all()
    if not workers:
        raise InsufficientData(f"no active workers at site '{site_id}' to plan leave/RDO for")

    window_end = request.planning_window.end
    worker_skills = _worker_skills(db, tenant_id, window_end)
    availability = _availability_rows_by_day(db, tenant_id)
    roles_by_worker = {w.worker_id: _eligible_roles(worker_skills.get(w.worker_id, set()), required_roles) for w in workers}

    solver = pywraplp.Solver.CreateSolver("CBC")
    x: dict[tuple[str, str], object] = {}
    priority_by_request: dict[tuple[str, str], float] = {}
    for worker in workers:
        for day in days:
            row = availability.get((worker.worker_id, day))
            if row is not None and row.status in REQUEST_STATUSES:
                x[(worker.worker_id, day)] = solver.BoolVar(f"x_{worker.worker_id}_{day}")
                priority_by_request[(worker.worker_id, day)] = row.preference or 0.0

    if not x:
        raise InsufficientData("no pending leave/RDO requests (Availability rows with status 'leave_requested'/'rdo_requested') found")

    short: dict[tuple[str, str], object] = {}
    objective_terms = []
    for (day, role), req in required.items():
        eligible_workers = [w for w in workers if role in roles_by_worker.get(w.worker_id, set())]
        # Baseline supply: eligible, not already unavailable, and not a
        # pending requester (their contribution depends on x, added next).
        baseline_supply = sum(
            1
            for worker in eligible_workers
            if (worker.worker_id, day) not in x
            and not (
                (row := availability.get((worker.worker_id, day))) is not None and row.status in ALREADY_UNAVAILABLE_STATUSES
            )
        )
        requester_vars = [x[(worker.worker_id, day)] for worker in eligible_workers if (worker.worker_id, day) in x]

        short[(day, role)] = solver.NumVar(0, solver.infinity(), f"short_{day}_{role}")
        # A requester contributes 1 to coverage only if their request is
        # rejected (x=0), i.e. (1 - x) per requester — avail_(i,d) is 1 for
        # every requester by construction (a request presumes they'd
        # otherwise be available), so y_(i,d) = avail*(1-x) = (1-x).
        solver.Add(baseline_supply + sum(1 - var for var in requester_vars) + short[(day, role)] >= req)
        objective_terms.append((short[(day, role)], shortage_penalty))

    for key, var in x.items():
        priority = priority_by_request[key]
        # Appendix A.7: costReject*(ask-x) - priority*x, with ask=1 for
        # every variable here (we only create x for actual requests) —
        # (ask-x) = (1-x), so the x-coefficient is -(rejection_penalty + priority);
        # the constant rejection_penalty*ask term is tracked separately below
        # for reporting, since it doesn't affect the optimal x.
        objective_terms.append((var, -(rejection_penalty + priority)))

    solver.Minimize(sum(coeff * var for var, coeff in objective_terms))
    status = solver.Solve()
    if status not in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        raise InsufficientData("leave/RDO MILP did not return a usable solution")

    decisions = []
    approved_count = 0
    for (worker_id, day), var in x.items():
        approved = var.solution_value() > 0.5
        approved_count += int(approved)
        row = availability.get((worker_id, day))
        decisions.append(
            {
                "worker_id": worker_id,
                "day": day,
                "request_type": "leave" if row.status == "leave_requested" else "rdo",
                "approved": approved,
            }
        )
    rejected_count = len(decisions) - approved_count
    total_shortfall = sum(var.solution_value() for var in short.values())
    total_required = sum(required.values())
    coverage_pct = round(100 * max(0.0, 1 - total_shortfall / total_required), 2) if total_required else 100.0

    # Baseline: approve every request regardless of coverage impact — the
    # naive policy this model is meant to improve on.
    baseline_shortfall = 0.0
    for (day, role), req in required.items():
        eligible_workers = [w for w in workers if role in roles_by_worker.get(w.worker_id, set())]
        baseline_supply = sum(
            1
            for worker in eligible_workers
            if (worker.worker_id, day) not in x
            and not (
                (row := availability.get((worker.worker_id, day))) is not None and row.status in ALREADY_UNAVAILABLE_STATUSES
            )
        )
        baseline_shortfall += max(0, req - baseline_supply)

    return SolverOutcome(
        result={
            "decisions": decisions,
            "kpis": {
                "approved_count": approved_count,
                "rejected_count": rejected_count,
                "coverage_pct": coverage_pct,
                "remaining_shortfall": round(total_shortfall, 2),
            },
        },
        baseline={"method": "approve_all_requests", "shortfall_count": round(baseline_shortfall, 2)},
        proposed={"method": "milp_balanced_approval", "shortfall_count": round(total_shortfall, 2)},
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
            f"MILP over {len(x)} pending requests across {len(workers)} workers; {approved_count} approved, {rejected_count} rejected",
        ]
        + ([f"{round(total_shortfall, 1)} worker-shifts of coverage shortfall remain even after rejections"] if total_shortfall > 0 else []),
        missing_evidence=labour_req.missing_evidence,
        assumptions=labour_req.assumptions
        + [
            f"policy '{policy.policy_version}': shortage penalty ${shortage_penalty}/worker, rejection penalty ${rejection_penalty}/request",
            "approval priority reuses Availability.preference on the request row",
            "required coverage per role = ceil(labour-requirement hours / hours_per_worker_per_day)",
        ],
        feasibility="feasible_with_slack" if total_shortfall > 0 else "feasible",
    )
