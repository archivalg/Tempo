"""Order-driven workload (order-driven-planning Stage 2): deadline-aware scheduling of known orders
against real worker activity rates, instead of only period-bucket forecasts. See
docs/order-driven-planning.md for scope and acceptance scenarios.

Deliberately NOT a MILP: Stage 2 proves deadline/rate/precedence/conversion math with a direct
calculation (one order's steps are independent of every other order's — brief: "packing one
completed order need not wait for every order to be picked"). Multi-order contention for the same
pool of workers, equipment limits and headcount caps are Stage 3 (see docs/order-driven-planning.md);
every worker eligible for an activity is treated as available for the whole planning window.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import Worker, WorkerPerformanceProfile, WorkStandard
from app.models.orders import Order, ProcessStep, UnitConversion, WorkerActivityRate
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome

DEFAULT_TARGET_UNIT = "units"


@dataclass(frozen=True)
class WorkerCapacity:
    worker_id: str
    rate_per_hour: float
    rate_source: str


@dataclass
class ActivityStepPlan:
    sequence: int
    activity: str
    release_at: datetime
    due_at: datetime
    quantity: float
    available_hours: float
    productive_hours_used: float
    completed_at: datetime | None
    shortfall_quantity: float


def resolve_activity_rate(*, personal_rate: float | None, role_rate: float | None, day_rate: float | None,
                           standard_rate_per_hour: float | None, productivity_index: float | None) -> tuple[float, str]:
    """Precedence per the brief: personal activity rate > compatible personal role rate > effective
    weekday activity standard > activity standard. `productivity_index` only adjusts the last of
    these (legacy fallback), and never stacks with a personal rate."""
    if personal_rate is not None:
        return personal_rate, "personal_activity_rate"
    if role_rate is not None:
        return role_rate, "personal_role_rate"
    if day_rate is not None:
        return day_rate, "weekday_activity_standard"
    if standard_rate_per_hour is not None:
        if productivity_index:
            return standard_rate_per_hour * productivity_index, "activity_standard_adjusted_by_productivity_index"
        return standard_rate_per_hour, "activity_standard"
    raise ValueError("no rate available for this worker/activity")


def resolve_order_quantity(*, units: float | None, lines: float | None, activity: str,
                            conversions: dict[tuple[str | None, str, str], float], target_unit: str = DEFAULT_TARGET_UNIT) -> float:
    """`units` is authoritative when present — `lines` is never added to it (brief: "When 32 units
    are already supplied, total workload remains 32"). Converting `lines` requires an explicit
    activity-specific or global factor; a missing path is rejected, never guessed."""
    if units is not None:
        return units
    if lines is None:
        raise ValueError("order has neither units nor lines — nothing to schedule")
    factor = conversions.get((activity, "lines", target_unit), conversions.get((None, "lines", target_unit)))
    if factor is None:
        raise ValueError(f"no unit conversion from 'lines' to '{target_unit}' for activity '{activity}' (and no global conversion) — add one before this order can be planned")
    return lines * factor


def schedule_activity(*, sequence: int, activity: str, quantity: float, release_at: datetime, due_at: datetime,
                       workers: list[WorkerCapacity]) -> ActivityStepPlan:
    if due_at <= release_at:
        return ActivityStepPlan(sequence=sequence, activity=activity, release_at=release_at, due_at=due_at, quantity=quantity,
                                 available_hours=0.0, productive_hours_used=0.0, completed_at=None, shortfall_quantity=quantity)
    available_hours = (due_at - release_at).total_seconds() / 3600
    total_rate = sum(w.rate_per_hour for w in workers)
    if total_rate <= 0:
        return ActivityStepPlan(sequence=sequence, activity=activity, release_at=release_at, due_at=due_at, quantity=quantity,
                                 available_hours=available_hours, productive_hours_used=0.0, completed_at=None, shortfall_quantity=quantity)
    max_units_by_due = total_rate * available_hours
    if quantity <= max_units_by_due + 1e-9:
        hours_needed = quantity / total_rate
        return ActivityStepPlan(sequence=sequence, activity=activity, release_at=release_at, due_at=due_at, quantity=quantity,
                                 available_hours=available_hours, productive_hours_used=round(hours_needed, 6),
                                 completed_at=release_at + timedelta(hours=hours_needed), shortfall_quantity=0.0)
    shortfall = quantity - max_units_by_due
    return ActivityStepPlan(sequence=sequence, activity=activity, release_at=release_at, due_at=due_at, quantity=quantity,
                             available_hours=available_hours, productive_hours_used=round(available_hours, 6),
                             completed_at=None, shortfall_quantity=round(shortfall, 6))


def plan_order_steps(*, order_received: datetime, despatch_due: datetime, quantity: float,
                      steps: list[tuple[int, str, int]], workers_by_activity: dict[str, list[WorkerCapacity]]) -> list[ActivityStepPlan]:
    """Each step releases no earlier than the previous step's completion plus its lag (finish-to-
    start, scoped to this order only — a different order's steps never share this cursor)."""
    plans: list[ActivityStepPlan] = []
    cursor = order_received
    for sequence, activity, lag_minutes in sorted(steps, key=lambda s: s[0]):
        release = cursor + timedelta(minutes=lag_minutes)
        plan = schedule_activity(sequence=sequence, activity=activity, quantity=quantity, release_at=release, due_at=despatch_due,
                                  workers=workers_by_activity.get(activity, []))
        plans.append(plan)
        cursor = plan.completed_at if plan.completed_at is not None else despatch_due
    return plans


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def solve_order_fulfillment(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    site_id = site_ids[0]
    window = request.planning_window
    orders = list(db.scalars(select(Order).where(
        Order.tenant_id == tenant_id, Order.site_id == site_id, Order.status == "open",
        Order.order_received < window.end, Order.despatch_due > window.start,
    )))
    if not orders:
        raise InsufficientData(f"no open orders at site '{site_id}' within the planning window")

    workers = list(db.scalars(select(Worker).where(Worker.tenant_id == tenant_id, Worker.home_site == site_id, Worker.status == "active")))
    worker_ids = [w.worker_id for w in workers] or [""]
    today = datetime.now(timezone.utc).date()
    personal_rates: dict[tuple[str, str], float] = {}
    for r in sorted(db.scalars(select(WorkerActivityRate).where(WorkerActivityRate.tenant_id == tenant_id, WorkerActivityRate.worker_id.in_(worker_ids))),
                     key=lambda r: r.effective_from):
        if r.effective_from <= today and (r.effective_to is None or r.effective_to > today):
            personal_rates[(r.worker_id, r.activity)] = r.rate_per_hour  # later effective_from wins (sorted ascending, last write wins)

    standards = {w.activity: w.time_per_unit_seconds for w in db.scalars(select(WorkStandard).where(WorkStandard.tenant_id == tenant_id))}
    productivity = {p.worker_id: p.productivity_index for p in db.scalars(select(WorkerPerformanceProfile).where(WorkerPerformanceProfile.tenant_id == tenant_id))}
    conversions = {(c.activity, c.from_unit, c.to_unit): c.factor for c in db.scalars(select(UnitConversion).where(UnitConversion.tenant_id == tenant_id))}

    order_results: list[dict] = []
    missing_evidence: list[str] = []
    total_shortfall = total_quantity = 0.0
    for order in orders:
        steps = list(db.scalars(select(ProcessStep).where(ProcessStep.tenant_id == tenant_id, ProcessStep.process_template_id == order.process_template_id).order_by(ProcessStep.sequence)))
        if not steps:
            missing_evidence.append(f"order '{order.order_ref}' has a process template with no steps — skipped")
            continue
        try:
            quantity = resolve_order_quantity(units=order.units, lines=order.lines, activity=steps[0].activity, conversions=conversions, target_unit=order.unit)
        except ValueError as exc:
            missing_evidence.append(f"order '{order.order_ref}': {exc}")
            continue

        workers_by_activity: dict[str, list[WorkerCapacity]] = {}
        for step in steps:
            caps: list[WorkerCapacity] = []
            for w in workers:
                personal = personal_rates.get((w.worker_id, step.activity))
                std_seconds = standards.get(step.activity)
                standard_rate = 3600 / std_seconds if std_seconds else None
                try:
                    rate, source = resolve_activity_rate(personal_rate=personal, role_rate=None, day_rate=None,
                                                          standard_rate_per_hour=standard_rate, productivity_index=productivity.get(w.worker_id))
                except ValueError:
                    continue  # not eligible / no data for this activity at all
                caps.append(WorkerCapacity(worker_id=w.worker_id, rate_per_hour=rate, rate_source=source))
            workers_by_activity[step.activity] = caps
            if not caps:
                missing_evidence.append(f"order '{order.order_ref}': no worker or work standard covers activity '{step.activity}' at site '{site_id}'")

        plans = plan_order_steps(order_received=_aware(order.order_received), despatch_due=_aware(order.despatch_due), quantity=quantity,
                                  steps=[(s.sequence, s.activity, s.lag_minutes) for s in steps], workers_by_activity=workers_by_activity)
        shortfall = sum(p.shortfall_quantity for p in plans)
        total_shortfall += shortfall
        total_quantity += quantity
        order_results.append({
            "order_ref": order.order_ref, "despatch_due": order.despatch_due.isoformat(), "quantity": round(quantity, 3),
            "steps": [{"sequence": p.sequence, "activity": p.activity, "release_at": p.release_at.isoformat(),
                       "completed_at": p.completed_at.isoformat() if p.completed_at else None,
                       "productive_hours": p.productive_hours_used, "shortfall_quantity": p.shortfall_quantity} for p in plans],
            "on_time": shortfall == 0,
            "shortfall_quantity": round(shortfall, 3),
        })

    coverage = 1.0 if total_quantity == 0 else max(0.0, 1 - total_shortfall / total_quantity)
    return SolverOutcome(
        result={"orders": order_results, "kpis": {"orders_planned": len(order_results), "total_shortfall_quantity": round(total_shortfall, 3), "coverage_pct": round(coverage * 100, 2)}},
        baseline={"method": "order_driven", "orders_in_window": len(orders)},
        proposed={"method": "order_driven_deadline_scheduling", "orders_planned": len(order_results)},
        delta={"orders_shortfall": sum(1 for r in order_results if not r["on_time"])},
        confidence_components=ConfidenceComponents(
            completeness=1.0 if not missing_evidence else round(len(order_results) / len(orders), 4),
            freshness=1.0, mapping_quality=1.0, forecast_validation=1.0, constraint_coverage=1.0,
            solution_quality=1.0 if total_shortfall == 0 else 0.5,
        ),
        primary_drivers=[f"Planned {len(order_results)} of {len(orders)} order(s); {round(total_shortfall, 1)} unit(s) shortfall" if total_shortfall else f"Planned {len(order_results)} of {len(orders)} order(s) fully on time"],
        missing_evidence=missing_evidence,
        assumptions=["every active worker eligible for an activity is treated as available for the whole planning window — availability/roster intersection and multi-order worker contention are Stage 3"],
        feasibility="feasible_with_slack" if total_shortfall > 0 else "feasible",
    )
