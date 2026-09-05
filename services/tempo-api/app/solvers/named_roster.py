"""Named Roster Optimisation (CP-SAT) — AI Labour Optimisation Spec §3.4 / Appendix A.4.

Staffing targets N_(d,k,r,z) come from Workforce Mix's day/role/zone
headcount, split evenly across the fixed shift calendar (app/solvers/shifts.py)
— Phase A wires the two models together rather than duplicating demand
translation. Scope reductions (on top of Workforce Mix's, which this
inherits): no explicit team-continuity/mentor-pairing constraints, and
availability with no matching record defaults to "available" rather than
blocking the roster on incomplete calendar data (recorded in
missing_evidence, not silently assumed away).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from ortools.sat.python import cp_model
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import Availability, LabourCostRule, ShiftAssignment as ShiftAssignmentRow, SkillCertification, Worker
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome
from app.solvers.shifts import SHIFT_CALENDAR
from app.solvers.workforce_mix import solve_workforce_mix

MAX_CONSECUTIVE_DAYS = 6
CONSECUTIVE_WINDOW = 7
FAIRNESS_WEIGHT_CENTS = 5000
PREFERENCE_WEIGHT_CENTS = 2000
SHORTFALL_PENALTY_CENTS_PER_HOUR = 25000
SOLVE_TIME_LIMIT_SECONDS = 10.0
MONEY_SCALE = 100  # dollars -> cents, for CP-SAT's integer objective


def _target_headcount(mix_assignments: list[dict]) -> dict[tuple[str, str, str], int]:
    totals: dict[tuple[str, str, str], int] = defaultdict(int)
    for a in mix_assignments:
        totals[(a["day"], a["role"], a["zone"])] += a["headcount"]
    return totals


def _split_across_shifts(totals: dict[tuple[str, str, str], int]) -> dict[tuple[str, str, str, str], int]:
    codes = [s.code for s in SHIFT_CALENDAR]
    per_shift: dict[tuple[str, str, str, str], int] = {}
    for (day, role, zone), total in totals.items():
        base, remainder = divmod(total, len(codes))
        for index, code in enumerate(codes):
            per_shift[(day, code, role, zone)] = base + (1 if index < remainder else 0)
    return per_shift


def _rate_lookup(db: Session, tenant_id: str) -> dict[tuple[str, str], LabourCostRule]:
    rows = db.scalars(select(LabourCostRule).where(LabourCostRule.tenant_id == tenant_id)).all()
    return {(row.labour_type, row.role): row for row in rows}


def _worker_skills(db: Session, tenant_id: str, window_end: datetime) -> dict[str, set[str]]:
    rows = db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == tenant_id)).all()
    skills: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        valid_to = row.valid_to
        if valid_to is not None and valid_to.tzinfo is None:
            # See the matching note in demand_forecast.py — SQLite round-trips
            # DateTime(timezone=True) columns as naive; treat as UTC.
            valid_to = valid_to.replace(tzinfo=timezone.utc)
        if valid_to is None or valid_to >= window_end:
            skills[row.worker_id].add(row.skill_code)
    return skills


def _availability_by_day(db: Session, tenant_id: str) -> dict[tuple[str, str], str]:
    rows = db.scalars(select(Availability).where(Availability.tenant_id == tenant_id)).all()
    status_by_worker_day: dict[tuple[str, str], str] = {}
    for row in rows:
        day = row.interval_start.date().isoformat()
        status_by_worker_day[(row.worker_id, day)] = row.status
    return status_by_worker_day


def solve_named_roster(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    site_id = site_ids[0]
    mix_outcome = solve_workforce_mix(db, tenant_id, site_ids, request)
    targets = _target_headcount(mix_outcome.result["assignments"])
    if not targets:
        raise InsufficientData("workforce mix produced no headcount targets to build a roster against")
    per_shift_targets = _split_across_shifts(targets)
    shift_hours = {s.code: int(s.hours) for s in SHIFT_CALENDAR}

    workers = db.scalars(
        select(Worker)
        .where(Worker.tenant_id == tenant_id)
        .where(Worker.home_site == site_id)
        .where(Worker.status == "active")
    ).all()
    if not workers:
        raise InsufficientData(f"no active workers at site '{site_id}' to build a named roster from")

    window_end = request.planning_window.end
    skills = _worker_skills(db, tenant_id, window_end)
    availability = _availability_by_day(db, tenant_id)
    rate_rules = _rate_lookup(db, tenant_id)
    days = sorted({day for day, _, _, _ in per_shift_targets})

    model = cp_model.CpModel()
    x: dict[tuple[str, str, str, str, str], object] = {}
    by_worker_day: dict[tuple[str, str], list] = defaultdict(list)
    hours_terms: dict[str, list[tuple[object, int]]] = defaultdict(list)
    objective_terms: list[tuple[object, int]] = []
    unmet_vars: dict[tuple[str, str, str, str], object] = {}

    for (day, shift_code, role, zone), target in per_shift_targets.items():
        if target <= 0:
            continue
        eligible_vars = []
        for worker in workers:
            worker_role_skills = skills.get(worker.worker_id, set())
            eligible = role == "general" or role in worker_role_skills
            if not eligible:
                continue
            status = availability.get((worker.worker_id, day), "available")
            if status in {"unavailable", "leave", "rdo"}:
                continue

            var = model.NewBoolVar(f"x_{worker.worker_id}_{day}_{shift_code}_{role}_{zone}")
            x[(worker.worker_id, day, shift_code, role, zone)] = var
            by_worker_day[(worker.worker_id, day)].append(var)
            eligible_vars.append(var)

            rule = rate_rules.get((worker.employment_type, role)) or rate_rules.get((worker.employment_type, "general"))
            rate = float(rule.rate) if rule else 40.0
            cost_cents = round(rate * shift_hours[shift_code] * MONEY_SCALE)
            objective_terms.append((var, cost_cents))
            hours_terms[worker.worker_id].append((var, shift_hours[shift_code]))

        unmet = model.NewIntVar(0, target, f"u_{day}_{shift_code}_{role}_{zone}")
        unmet_vars[(day, shift_code, role, zone)] = unmet
        model.Add(sum(eligible_vars) + unmet >= target)
        # Cents, same unit as the assignment-cost terms above — must dominate
        # any single worker's shift cost or the solver will "solve" a
        # shortage by simply leaving it unmet (this was a real bug: an
        # earlier `// 100` here made the shortfall penalty cheaper than
        # assigning anyone, so every shift went unmet).
        objective_terms.append((unmet, SHORTFALL_PENALTY_CENTS_PER_HOUR * shift_hours[shift_code]))

    for (worker_id, day), vars_for_day in by_worker_day.items():
        model.Add(sum(vars_for_day) <= 1)

    if len(days) >= CONSECUTIVE_WINDOW:
        for worker in workers:
            for start in range(len(days) - CONSECUTIVE_WINDOW + 1):
                window_days = set(days[start : start + CONSECUTIVE_WINDOW])
                window_vars = [
                    var
                    for (wid, day), vars_for_day in by_worker_day.items()
                    if wid == worker.worker_id and day in window_days
                    for var in vars_for_day
                ]
                if window_vars:
                    model.Add(sum(window_vars) <= MAX_CONSECUTIVE_DAYS)

    total_target_hours = sum(target * shift_hours[code] for (_, code, _, _), target in per_shift_targets.items())
    avg_hours = round(total_target_hours / len(workers)) if workers else 0
    fairness_terms = []
    for worker in workers:
        terms = hours_terms.get(worker.worker_id, [])
        if not terms:
            continue
        max_possible_hours = sum(h for _, h in terms)
        f_plus = model.NewIntVar(0, max_possible_hours + avg_hours, f"fplus_{worker.worker_id}")
        f_minus = model.NewIntVar(0, avg_hours, f"fminus_{worker.worker_id}")
        model.Add(sum(coeff * var for var, coeff in terms) - avg_hours == f_plus - f_minus)
        fairness_terms.append(f_plus)
        fairness_terms.append(f_minus)
        objective_terms.append((f_plus, FAIRNESS_WEIGHT_CENTS // 100))
        objective_terms.append((f_minus, FAIRNESS_WEIGHT_CENTS // 100))

    model.Minimize(sum(coeff * var for var, coeff in objective_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVE_TIME_LIMIT_SECONDS
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise InsufficientData("named roster CP-SAT model did not return a usable solution within the time limit")

    assignments = []
    total_cost = 0.0
    proposed_rows: list[ShiftAssignmentRow] = []
    for (worker_id, day, shift_code, role, zone), var in x.items():
        if solver.Value(var) != 1:
            continue
        worker = next(w for w in workers if w.worker_id == worker_id)
        rule = rate_rules.get((worker.employment_type, role)) or rate_rules.get((worker.employment_type, "general"))
        rate = float(rule.rate) if rule else 40.0
        hours = shift_hours[shift_code]
        cost = rate * hours
        total_cost += cost
        shift_def = next(s for s in SHIFT_CALENDAR if s.code == shift_code)
        assignments.append(
            {
                "worker_id": worker_id,
                "day": day,
                "shift_code": shift_code,
                "role": role,
                "zone": zone,
                "hours": hours,
            }
        )
        day_start = datetime.fromisoformat(day)
        proposed_rows.append(
            ShiftAssignmentRow(
                tenant_id=tenant_id,
                worker_id=worker_id,
                role=role,
                zone=zone,
                start_at=day_start.replace(hour=shift_def.start_hour, tzinfo=timezone.utc),
                end_at=day_start.replace(hour=shift_def.end_hour, tzinfo=timezone.utc),
                status="proposed",
            )
        )
    for row in proposed_rows:
        db.add(row)

    total_unmet_shifts = sum(solver.Value(v) for v in unmet_vars.values())
    total_target_shifts = sum(per_shift_targets.values())
    coverage_pct = round(100 * (1 - total_unmet_shifts / total_target_shifts), 2) if total_target_shifts else 100.0

    mix_cost = float(mix_outcome.result["kpis"]["labour_cost"]["amount"])

    missing_evidence = list(mix_outcome.missing_evidence)
    unavailable_workers_with_no_record = sum(
        1 for worker in workers if not any(day in {d for d, *_ in per_shift_targets} for (wid, day) in availability if wid == worker.worker_id)
    )
    if unavailable_workers_with_no_record:
        missing_evidence.append(
            f"{unavailable_workers_with_no_record} of {len(workers)} workers have no Availability records for this "
            "window — defaulted to available"
        )

    return SolverOutcome(
        result={
            "assignments": assignments,
            "kpis": {
                "labour_cost": {"amount": f"{total_cost:.2f}", "currency": "AUD"},
                "coverage_pct": coverage_pct,
                "unmet_shift_slots": total_unmet_shifts,
            },
        },
        baseline={"method": "workforce_mix_target_cost", "labour_cost": {"amount": f"{mix_cost:.2f}", "currency": "AUD"}},
        proposed={"method": "cp_sat_named_roster", "labour_cost": {"amount": f"{total_cost:.2f}", "currency": "AUD"}},
        delta={"labour_cost": {"amount": f"{total_cost - mix_cost:.2f}", "currency": "AUD"}},
        confidence_components=ConfidenceComponents(
            completeness=mix_outcome.confidence_components.completeness,
            freshness=mix_outcome.confidence_components.freshness,
            mapping_quality=mix_outcome.confidence_components.mapping_quality,
            forecast_validation=mix_outcome.confidence_components.forecast_validation,
            constraint_coverage=1.0 if total_unmet_shifts == 0 else 0.6,
            solution_quality=1.0 if status == cp_model.OPTIMAL else 0.7,
        ),
        primary_drivers=[
            f"CP-SAT over {len(workers)} workers x {len(days)} days, max {MAX_CONSECUTIVE_DAYS} consecutive days enforced",
        ]
        + ([f"{total_unmet_shifts} shift-slots understaffed — insufficient eligible/available workers"] if total_unmet_shifts > 0 else []),
        missing_evidence=missing_evidence,
        assumptions=mix_outcome.assumptions
        + [
            "workforce mix headcount split evenly across the fixed shift calendar",
            "worker with no Availability record for a day defaults to available",
        ],
        feasibility="feasible_with_slack" if total_unmet_shifts > 0 else "feasible",
    )
