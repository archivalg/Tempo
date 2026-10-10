"""Order-driven workload (order-driven-planning Stage 2, extended by the integration increment):
deadline-aware scheduling of known orders against real worker activity rates, shared across a single
coherent plan with calendars, availability, indirect coverage, equipment, headcount limits,
absenteeism, congestion/off-task loss, staging capacity and grade-aware costing. See
docs/order-driven-planning.md for scope, the capability matrix and acceptance scenarios.

Deliberately NOT a MILP: this is a greedy, priority-ordered, interval-by-interval allocator, not a
globally optimal solver. It is still a REAL shared-resource scheduler — workers and equipment are
finite, consumed exactly once per interval, and never double-booked (`_worker_busy_until`) — not a
per-order independent calculation. `resolve_activity_rate` / `resolve_order_quantity` /
`schedule_activity` / `plan_order_steps` below remain the original, still-tested, infinite-capacity
single-order building blocks (used directly by the Stage 2 unit tests); `solve_order_fulfillment`
itself now runs the shared, interval-by-interval allocator described below instead of calling them.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.availability_pattern import WeeklyAvailabilityPattern
from app.models.canonical import Availability, DemandBucket, LabourCostRule, SkillCertification, Worker, WorkerPerformanceProfile, WorkStandard
from app.models.constraints import AbsenteeismRule as AbsenteeismRuleModel
from app.models.constraints import AwardRule as AwardRuleModel
from app.models.constraints import Equipment as EquipmentModel
from app.models.constraints import FillPriority, HeadcountLimit
from app.models.indirect import IndirectHeadcountRequirement
from app.models.orders import DayRate, Order, ProcessStep, UnitConversion, WorkerActivityRate
from app.models.scheduling import ShiftBreak, ShiftTemplate, OperatingCalendarDay, WEEKDAYS
from app.models.stage4 import ProductivityLoss
from app.models.stage4 import StagingCapacity as StagingCapacityModel
from app.models.stage4 import StagingMovement as StagingMovementModel
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverInfeasible, SolverOutcome
from app.solvers.constraints import (
    AbsenteeismRule,
    AmbiguousAbsenteeismRule,
    EquipmentAssignment,
    check_equipment_capacity,
    fill_priority_key,
    resolve_absenteeism,
)
from app.solvers.losses import (
    CostRule,
    ProductivityLossRule,
    StagingMovement as StagingMovementCalc,
    StagingUnitMismatch,
    apply_congestion,
    apply_off_task_hours,
    check_staging_capacity,
    compute_staging_occupancy,
    labour_cost,
    resolve_cost_rate,
    resolve_productivity_loss,
)
from app.solvers.shifts import BreakDefinition, hhmm_to_minutes, shift_elapsed_minutes, shift_hours, shift_template_bounds_utc

DEFAULT_TARGET_UNIT = "units"

# Direct work is allocated at this granularity within a shift instance (brief: "Allow dependent
# steps to start at the next scheduling interval... Do not force them to wait until the next
# shift"). A predecessor finishing mid-shift lets its successor start at the next multiple of this
# many minutes, not at the next shift. Indirect coverage reservation still operates at whole-shift
# granularity (a supervisor covers a shift, not a rotating hour). Smaller values schedule more
# precisely at the cost of more sub-intervals to iterate (O(shift_minutes / granularity) per shift,
# per site, per run) — 60 is a deliberate balance, not a hard requirement.
SCHEDULING_INTERVAL_MINUTES = 60


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


def _normalize_timezone_name(name: str) -> str:
    """A planning window's timezone is supposed to be an IANA name, but a caller's own
    `Intl.DateTimeFormat().resolvedOptions().timeZone` can resolve to a raw UTC-offset string (seen
    in at least one headless-browser environment) instead — e.g. "+00:00" rather than "UTC". Rather
    than crash with ZoneInfoNotFoundError, a whole-hour offset is mapped to its Etc/GMT equivalent
    (note: POSIX/tzdata's Etc/GMT sign convention is inverted) and anything else falls back to UTC."""
    import re
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", name.strip())
    if not m:
        return name
    sign, hh, mm = m.groups()
    hours = int(hh)
    if mm != "00" or hours == 0:
        return "UTC"
    return f"Etc/GMT{'-' if sign == '+' else '+'}{hours}"


# ============================================================================================ shared scheduler
@dataclass
class ShiftInstance:
    start_at: datetime
    end_at: datetime
    shift_code: str | None
    weekday: str | None
    paid_hours: float
    productive_hours: float
    breaks: list[BreakDefinition] = field(default_factory=list)


def _weekday_name(d) -> str:
    return WEEKDAYS[d.weekday()]


def _overlaps_time_window(inst_start_minute: int, inst_elapsed_minutes: int, req_start: str, req_end: str) -> bool:
    """Both windows expressed as minutes from the instance's own local midnight — a pragmatic
    same-day approximation (a requirement window is assumed to start on the instance's own local
    calendar date)."""
    req_elapsed = shift_elapsed_minutes(req_start, req_end)
    req_start_minute = hhmm_to_minutes(req_start)
    return inst_start_minute < req_start_minute + req_elapsed and req_start_minute < inst_start_minute + inst_elapsed_minutes


def _expand_shift_instances(db: Session, tenant_id: str, site_id: str, window, tz_name: str) -> list[ShiftInstance]:
    """Concrete UTC shift instances for the site within the window, from versioned ShiftTemplate/
    ShiftBreak/OperatingCalendarDay rows (order-driven-planning Stage 1). Empty if the tenant has not
    configured any shift templates — the caller falls back to one open interval and says so."""
    tz = ZoneInfo(tz_name)
    templates = list(db.scalars(select(ShiftTemplate).where(ShiftTemplate.tenant_id == tenant_id, ShiftTemplate.site_id == site_id)))
    if not templates:
        return []
    breaks_by_template: dict[str, list[BreakDefinition]] = defaultdict(list)
    for b in db.scalars(select(ShiftBreak).where(ShiftBreak.tenant_id == tenant_id, ShiftBreak.shift_template_id.in_([t.id for t in templates]))):
        breaks_by_template[b.shift_template_id].append(BreakDefinition(b.starts_after_minutes, b.duration_minutes, b.is_paid))
    calendar = {c.weekday: c for c in db.scalars(select(OperatingCalendarDay).where(OperatingCalendarDay.tenant_id == tenant_id, OperatingCalendarDay.site_id == site_id))}

    instances: list[ShiftInstance] = []
    d = (window.start.astimezone(tz) - timedelta(days=1)).date()
    end_date = window.end.astimezone(tz).date()
    while d <= end_date:
        wd = _weekday_name(d)
        cal = calendar.get(wd)
        if cal is not None and cal.is_closed:
            d += timedelta(days=1)
            continue
        for t in templates:
            if t.effective_from > d or (t.effective_to is not None and t.effective_to <= d):
                continue
            if wd not in (t.weekdays or []):
                continue
            start_utc, end_utc = shift_template_bounds_utc(d, t.start_time, t.end_time, tz_name)
            if end_utc <= window.start or start_utc >= window.end:
                continue
            elapsed = shift_elapsed_minutes(t.start_time, t.end_time)
            breaks = breaks_by_template.get(t.id, [])
            hours = shift_hours(elapsed, breaks)
            instances.append(ShiftInstance(start_at=start_utc, end_at=end_utc, shift_code=t.shift_code, weekday=wd,
                                           paid_hours=hours["paid_hours"], productive_hours=hours["productive_hours"], breaks=breaks))
        d += timedelta(days=1)
    instances.sort(key=lambda i: i.start_at)
    return instances


def _availability_blocked(worker_id: str, start: datetime, end: datetime, blocks: dict[str, list[tuple[datetime, datetime]]]) -> bool:
    return any(b_start < end and b_end > start for b_start, b_end in blocks.get(worker_id, []))


def _split_into_scheduling_intervals(instance: ShiftInstance, granularity_minutes: int) -> list[ShiftInstance]:
    """Divide a shift instance into fixed-size sub-intervals so a step can resume as soon as its
    predecessor finishes and its lag expires, instead of waiting for the next shift. Each break is
    apportioned to whichever sub-interval(s) it overlaps, so the sum of sub-interval paid/productive
    hours always equals the parent shift's (no double-deduction from splitting)."""
    windows = [(instance.start_at + timedelta(minutes=b.starts_after_minutes), instance.start_at + timedelta(minutes=b.starts_after_minutes + b.duration_minutes), b.is_paid)
               for b in instance.breaks]
    chunks: list[ShiftInstance] = []
    cursor = instance.start_at
    while cursor < instance.end_at:
        chunk_end = min(cursor + timedelta(minutes=granularity_minutes), instance.end_at)
        total_minutes = (chunk_end - cursor).total_seconds() / 60
        unpaid_overlap = paid_overlap = 0.0
        for b_start, b_end, is_paid in windows:
            overlap = max(0.0, (min(chunk_end, b_end) - max(cursor, b_start)).total_seconds() / 60)
            if overlap <= 0:
                continue
            if is_paid:
                paid_overlap += overlap
            else:
                unpaid_overlap += overlap
        chunks.append(ShiftInstance(start_at=cursor, end_at=chunk_end, shift_code=instance.shift_code, weekday=instance.weekday,
                                    paid_hours=(total_minutes - unpaid_overlap) / 60, productive_hours=(total_minutes - unpaid_overlap - paid_overlap) / 60))
        cursor = chunk_end
    return chunks


def _within_weekly_pattern(worker_id: str, weekday: str, local_start_minute: int, elapsed_minutes: int,
                           patterns: dict[tuple[str, str], tuple[bool, str | None, str | None]]) -> bool:
    """No row for this worker/weekday means no restriction (same "absence = available" convention as
    dated Availability). `available=False` blocks the whole day; a window requires full containment
    — a worker with a 06:00-14:00 window cannot pick up any part of a 14:00-22:00 interval — and an
    overnight window (latest_finish <= earliest_start) is handled the same way shift templates are."""
    pattern = patterns.get((worker_id, weekday))
    if pattern is None:
        return True
    available, earliest, latest = pattern
    if not available:
        return False
    if earliest is None or latest is None:
        return True
    window_elapsed = shift_elapsed_minutes(earliest, latest)
    window_start = hhmm_to_minutes(earliest)
    return window_start <= local_start_minute and local_start_minute + elapsed_minutes <= window_start + window_elapsed


@dataclass(frozen=True)
class _SyntheticDemand:
    """A forecast-derived demand line, scheduled through the same allocator as a real Order so it
    shares the same worker/equipment pool (order-driven-planning integration increment, priority 4)."""
    order_ref: str
    order_received: datetime
    despatch_due: datetime
    unit: str = DEFAULT_TARGET_UNIT


def solve_order_fulfillment(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    """One coherent plan: calendars/shifts/breaks, availability (dated and recurring weekly),
    dependencies/deadlines, personal rates/conversions, indirect coverage, fill priorities
    (activity and employment_type), absenteeism/equipment/headcount limits, congestion/off-task
    loss, staging capacity (which can delay a step's completion, not just report it afterwards),
    and grade-aware costing with paid-vs-productive hours all influence the same allocation.
    `demand_mode` lets known orders, forecast demand, or both (hybrid) share that same allocation —
    see docs/order-driven-planning.md for the capability matrix and remaining simplifications."""
    site_id = site_ids[0]
    window = request.planning_window
    tz_name = _normalize_timezone_name(window.timezone)
    tz = ZoneInfo(tz_name)
    demand_mode = request.input.demand_mode
    forecast_basis = request.input.forecast_basis or "additional"

    orders: list[Order] = []
    if demand_mode != "forecast_only":
        orders = list(db.scalars(select(Order).where(
            Order.tenant_id == tenant_id, Order.site_id == site_id, Order.status == "open",
            Order.order_received < window.end, Order.despatch_due > window.start,
        )))
        if not orders and demand_mode == "known_orders":
            raise InsufficientData(f"no open orders at site '{site_id}' within the planning window")

    missing_evidence: list[str] = []
    workers = list(db.scalars(select(Worker).where(Worker.tenant_id == tenant_id, Worker.home_site == site_id, Worker.status == "active")))
    worker_ids = [w.worker_id for w in workers] or [""]
    today = datetime.now(timezone.utc).date()

    personal_rates: dict[tuple[str, str], float] = {}
    for r in sorted(db.scalars(select(WorkerActivityRate).where(WorkerActivityRate.tenant_id == tenant_id, WorkerActivityRate.worker_id.in_(worker_ids))), key=lambda r: r.effective_from):
        if r.effective_from <= today and (r.effective_to is None or r.effective_to > today):
            personal_rates[(r.worker_id, r.activity)] = r.rate_per_hour

    standards = {w.activity: w.time_per_unit_seconds for w in db.scalars(select(WorkStandard).where(WorkStandard.tenant_id == tenant_id))}
    standard_function_flow = {w.activity: (w.function, w.flow) for w in db.scalars(select(WorkStandard).where(WorkStandard.tenant_id == tenant_id))}
    day_rates = {(d.activity, d.weekday): d.rate_per_hour for d in db.scalars(select(DayRate).where(DayRate.tenant_id == tenant_id))}
    award_rules = {a.award_code: a for a in db.scalars(select(AwardRuleModel).where(AwardRuleModel.tenant_id == tenant_id))}
    productivity = {p.worker_id: p.productivity_index for p in db.scalars(select(WorkerPerformanceProfile).where(WorkerPerformanceProfile.tenant_id == tenant_id))}
    conversions = {(c.activity, c.from_unit, c.to_unit): c.factor for c in db.scalars(select(UnitConversion).where(UnitConversion.tenant_id == tenant_id))}
    skills: dict[str, set[str]] = defaultdict(set)
    for s in db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == tenant_id, SkillCertification.worker_id.in_(worker_ids))):
        if _aware(s.valid_from) <= datetime.now(timezone.utc) and (s.valid_to is None or _aware(s.valid_to) > datetime.now(timezone.utc)):
            skills[s.worker_id].add(s.skill_code)

    avail_blocks: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for a in db.scalars(select(Availability).where(Availability.tenant_id == tenant_id, Availability.worker_id.in_(worker_ids),
                                                    Availability.status.in_(("unavailable", "leave", "rdo")))):
        avail_blocks[a.worker_id].append((_aware(a.interval_start), _aware(a.interval_end)))
    weekly_patterns: dict[tuple[str, str], tuple[bool, str | None, str | None]] = {
        (p.worker_id, p.weekday): (p.available, p.earliest_start, p.latest_finish)
        for p in db.scalars(select(WeeklyAvailabilityPattern).where(WeeklyAvailabilityPattern.tenant_id == tenant_id, WeeklyAvailabilityPattern.worker_id.in_(worker_ids)))
    }

    equipment_pools = {e.equipment_id: e.quantity_available for e in db.scalars(select(EquipmentModel).where(EquipmentModel.tenant_id == tenant_id, EquipmentModel.site_id == site_id))}
    headcount_limits: dict[tuple[str, str | None], tuple[int, int]] = {}
    for h in db.scalars(select(HeadcountLimit).where(HeadcountLimit.tenant_id == tenant_id, HeadcountLimit.site_id == site_id)):
        headcount_limits[(h.activity, h.shift_code)] = (h.min_headcount, h.max_headcount)
    fill_priorities = {(p.scope, p.value): p.priority for p in db.scalars(select(FillPriority).where(FillPriority.tenant_id == tenant_id))}
    absenteeism_rules = [AbsenteeismRule(site_id=a.site_id, activity=a.activity, weekday=a.weekday, shift_code=a.shift_code, absence_pct=a.absence_pct)
                         for a in db.scalars(select(AbsenteeismRuleModel).where(AbsenteeismRuleModel.tenant_id == tenant_id, AbsenteeismRuleModel.site_id == site_id))]
    loss_rules = [ProductivityLossRule(site_id=p.site_id, loss_type=p.loss_type, activity=p.activity, weekday=p.weekday, shift_code=p.shift_code, percent_loss=p.percent_loss, off_task_hours=p.off_task_hours)
                 for p in db.scalars(select(ProductivityLoss).where(ProductivityLoss.tenant_id == tenant_id, ProductivityLoss.site_id == site_id))]
    congestion_rules = [r for r in loss_rules if r.loss_type == "congestion"]
    offtask_rules = [r for r in loss_rules if r.loss_type == "off_task"]
    indirect_reqs = list(db.scalars(select(IndirectHeadcountRequirement).where(IndirectHeadcountRequirement.tenant_id == tenant_id, IndirectHeadcountRequirement.site_id == site_id)))
    cost_rules = [CostRule(labour_type=c.labour_type, role=c.role, rate=float(c.rate), position_grade=c.position_grade, provider_id=c.provider_id,
                           overtime_multiplier=float(c.overtime_multiplier) if c.overtime_multiplier else None, surcharge=float(c.surcharge) if c.surcharge else None, currency=c.currency)
                 for c in db.scalars(select(LabourCostRule).where(LabourCostRule.tenant_id == tenant_id))]
    staging_capacity = {c.zone_id: (c.capacity, c.unit) for c in db.scalars(select(StagingCapacityModel).where(StagingCapacityModel.tenant_id == tenant_id, StagingCapacityModel.site_id == site_id))}

    # Staging occupancy tracked live so a full zone can delay a step's completion instead of just
    # being reported as a violation afterwards (priority 3). Baseline = occupancy at window.start
    # from imported movements; later imported movements are applied as the schedule passes them.
    current_occupancy: dict[str, float] = {}
    pending_departures: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    by_zone: dict[str, list] = defaultdict(list)
    for m in db.scalars(select(StagingMovementModel).where(StagingMovementModel.tenant_id == tenant_id, StagingMovementModel.site_id == site_id)):
        by_zone[m.zone_id].append(m)
    for zone_id, movs in by_zone.items():
        occ = 0.0
        for m in sorted(movs, key=lambda m: _aware(m.occurred_at)):
            delta = m.quantity if m.movement_type in ("initial", "arrival") else -m.quantity
            t = _aware(m.occurred_at)
            if t <= window.start:
                occ += delta
            else:
                pending_departures[zone_id].append((t, delta))
        current_occupancy[zone_id] = occ
    staging_delays: list[dict] = []

    def _advance_staging(upto: datetime) -> None:
        for zone_id, events in pending_departures.items():
            while events and events[0][0] <= upto:
                t, delta = events.pop(0)
                current_occupancy[zone_id] = current_occupancy.get(zone_id, 0.0) + delta

    instances = _expand_shift_instances(db, tenant_id, site_id, window, tz_name)
    if not instances:
        missing_evidence.append("no shift templates configured for this site — treating each local calendar day in the window as one open interval with no break/operating-hours modelling")
        d = window.start.astimezone(tz).date()
        end_date = window.end.astimezone(tz).date()
        while d <= end_date:
            next_d = d + timedelta(days=1)
            local_midnight = datetime(d.year, d.month, d.day, tzinfo=tz).astimezone(timezone.utc)
            next_local_midnight = datetime(next_d.year, next_d.month, next_d.day, tzinfo=tz).astimezone(timezone.utc)
            day_start = max(window.start, local_midnight)
            day_end = min(window.end, next_local_midnight)
            if day_end > day_start:
                hours = (day_end - day_start).total_seconds() / 3600
                instances.append(ShiftInstance(start_at=day_start, end_at=day_end, shift_code=None, weekday=_weekday_name(d), paid_hours=hours, productive_hours=hours))
            d = next_d

    # --- per-order step state --------------------------------------------------------------------------------
    order_state: dict[str, dict] = {}
    known_quantity_by_activity_day: dict[tuple[str, object], float] = defaultdict(float)
    if demand_mode != "forecast_only":
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
            step_states = [{"sequence": s.sequence, "activity": s.activity, "lag_minutes": s.lag_minutes, "equipment_id": s.equipment_id, "zone_id": s.zone_id,
                             "remaining": quantity, "release_at": None, "completed_at": None, "hours": 0.0, "started_at": None} for s in steps]
            step_states[0]["release_at"] = _aware(order.order_received)
            order_state[order.id] = {"order": order, "quantity": quantity, "steps": step_states, "source": "order"}
            known_quantity_by_activity_day[(steps[0].activity, _aware(order.order_received).astimezone(tz).date())] += quantity

    # --- forecast demand, sharing the same allocation (priority 4: known-orders / forecast-only / hybrid) ------
    if demand_mode in ("forecast_only", "hybrid"):
        volume_by_activity_day: dict[tuple[str, object], float] = defaultdict(float)
        for b in db.scalars(select(DemandBucket).where(DemandBucket.tenant_id == tenant_id, DemandBucket.site_id == site_id,
                                                        DemandBucket.interval_start >= window.start, DemandBucket.interval_start < window.end)):
            volume_by_activity_day[(b.activity, _aware(b.interval_start).astimezone(tz).date())] += b.volume
        if demand_mode == "hybrid" and forecast_basis == "total":
            for key in list(volume_by_activity_day):
                volume_by_activity_day[key] = max(0.0, volume_by_activity_day[key] - known_quantity_by_activity_day.get(key, 0.0))
        for (activity, day), volume in volume_by_activity_day.items():
            if volume <= 1e-9:
                continue
            day_start = max(window.start, datetime(day.year, day.month, day.day, tzinfo=tz).astimezone(timezone.utc))
            day_end = min(window.end, day_start + timedelta(days=1))
            if day_end <= day_start:
                continue
            synthetic = _SyntheticDemand(order_ref=f"forecast:{activity}:{day.isoformat()}", order_received=day_start, despatch_due=day_end)
            order_state[synthetic.order_ref] = {"order": synthetic, "quantity": volume, "source": "forecast",
                                                "steps": [{"sequence": 1, "activity": activity, "lag_minutes": 0, "equipment_id": None, "zone_id": None,
                                                           "remaining": volume, "release_at": day_start, "completed_at": None, "hours": 0.0, "started_at": None}]}
        if demand_mode == "hybrid" and forecast_basis not in ("total", "additional"):
            missing_evidence.append("hybrid demand mode requires forecast_basis ('total' or 'additional') — defaulted to 'additional'")

    if not order_state:
        raise InsufficientData(f"no open orders and no forecast demand found at site '{site_id}' within the planning window for demand_mode '{demand_mode}'")

    # --- shared allocation loop --------------------------------------------------------------------------------
    worker_busy_until: dict[str, datetime] = {}
    equipment_events: list[EquipmentAssignment] = []
    staging_events: dict[str, list[StagingMovementCalc]] = defaultdict(list)
    activity_flags: dict[str, set[str]] = defaultdict(set)
    indirect_gaps: list[dict] = []
    headcount_violations: list[dict] = []
    total_cost = 0.0
    uncosted_paid_hours = 0.0
    total_paid_hours = 0.0
    total_productive_hours = 0.0
    indirect_paid_hours = 0.0
    any_assignment_made = False  # distinguishes "attempted but constrained to zero output" (feasible_with_slack,
    # already explained by indirect_coverage_gaps/headcount_violations/staging_delays/etc.) from
    # "nothing could even be attempted" (proven infeasibility, priority 1)

    daily_paid_hours: dict[tuple[str, object], float] = defaultdict(float)  # (worker_id, local date) → cumulative paid hours charged so far

    def _cost_for(w: Worker, hours: float, rate: float, at: datetime) -> float:
        """Applies the worker's award overtime_multiplier (if any) to whatever portion of `hours`
        falls beyond their ordinary_hours_per_day for that local date — an award name alone changes
        nothing; only a matching AwardRule row does (priority 17)."""
        award = award_rules.get(w.award) if w.award else None
        if award is None:
            return labour_cost(paid_hours=hours, rate_per_hour=rate)
        local_date = at.astimezone(tz).date()
        key = (w.worker_id, local_date)
        already = daily_paid_hours[key]
        daily_paid_hours[key] = already + hours
        ordinary_remaining = max(0.0, award.ordinary_hours_per_day - already)
        overtime_hours = max(0.0, hours - ordinary_remaining)
        return labour_cost(paid_hours=hours, rate_per_hour=rate, overtime_hours=overtime_hours, overtime_multiplier=award.overtime_multiplier)

    def _blocked(worker_id: str, weekday: str, start: datetime, end: datetime) -> bool:
        if _availability_blocked(worker_id, start, end, avail_blocks):
            return True
        local = start.astimezone(tz)
        start_minute = local.hour * 60 + local.minute
        elapsed = int((end - start).total_seconds() / 60)
        return not _within_weekly_pattern(worker_id, weekday, start_minute, elapsed, weekly_patterns)

    for instance in instances:
        weekday = instance.weekday or _weekday_name(instance.start_at.astimezone(tz).date())
        local_start = instance.start_at.astimezone(tz)
        inst_start_minute = local_start.hour * 60 + local_start.minute
        inst_elapsed_minutes = int((instance.end_at - instance.start_at).total_seconds() / 60)

        # Indirect coverage reserves a worker for the WHOLE shift instance (a supervisor covers a
        # shift, not a rotating sub-interval) — direct work below instead uses finer sub-intervals.
        reserved: set[str] = set()
        for req in indirect_reqs:
            if req.weekday != weekday or not _overlaps_time_window(inst_start_minute, inst_elapsed_minutes, req.start_time, req.end_time):
                continue
            eligible = [w for w in workers if req.role in skills.get(w.worker_id, set()) and w.worker_id not in reserved
                       and worker_busy_until.get(w.worker_id, datetime.min.replace(tzinfo=timezone.utc)) <= instance.start_at and not _blocked(w.worker_id, weekday, instance.start_at, instance.end_at)]
            chosen = sorted(eligible, key=lambda w: w.worker_id)[: req.headcount]
            if len(chosen) < req.headcount:
                indirect_gaps.append({"role": req.role, "weekday": weekday, "interval_start": instance.start_at.isoformat(), "reason": "missing_qualified_workers", "shortfall": req.headcount - len(chosen)})
            if instance.breaks:
                relief_pool = [w for w in eligible if w not in chosen]
                if req.headcount > 0 and not relief_pool:
                    indirect_gaps.append({"role": req.role, "weekday": weekday, "interval_start": instance.start_at.isoformat(), "reason": "no_break_relief"})
            if chosen:
                any_assignment_made = True
            for w in chosen:
                reserved.add(w.worker_id)
                worker_busy_until[w.worker_id] = instance.end_at
                cr = resolve_cost_rate(cost_rules, labour_type=w.employment_type, role=req.role, position_grade=w.position_grade, provider_id=w.provider_id)
                total_paid_hours += instance.paid_hours
                indirect_paid_hours += instance.paid_hours
                if cr is None:
                    uncosted_paid_hours += instance.paid_hours
                    missing_evidence.append(f"no cost rate configured for indirect role '{req.role}' ({w.employment_type}) — cost is incomplete")
                else:
                    total_cost += _cost_for(w, instance.paid_hours, cr.rate, instance.start_at)

        # Direct work is allocated sub-interval by sub-interval so a dependent step can resume as
        # soon as its predecessor finishes and its lag expires, rather than waiting for the next
        # shift (priority 1). SCHEDULING_INTERVAL_MINUTES documents the granularity.
        for sub in _split_into_scheduling_intervals(instance, SCHEDULING_INTERVAL_MINUTES):
            _advance_staging(sub.start_at)
            equipment_remaining = dict(equipment_pools)  # shared across EVERY activity in this sub-interval, not just the one reading it last (priority 10)
            available_now = [w for w in workers if w.worker_id not in reserved
                             and worker_busy_until.get(w.worker_id, datetime.min.replace(tzinfo=timezone.utc)) <= sub.start_at and not _blocked(w.worker_id, weekday, sub.start_at, sub.end_at)]

            ready_by_activity: dict[str, list[tuple[str, dict]]] = defaultdict(list)
            for order_id, state in order_state.items():
                step = next((s for s in state["steps"] if s["remaining"] > 1e-9), None)
                if step is None or step["release_at"] is None:
                    continue
                if step["release_at"] < sub.end_at and sub.start_at < _aware(state["order"].despatch_due):
                    ready_by_activity[step["activity"]].append((order_id, step))

            def _activity_priority(activity: str) -> tuple[int, str]:
                return (fill_priority_key(fill_priorities, scope="activity", value=activity), activity)

            for activity in sorted(ready_by_activity, key=_activity_priority):
                tasks = sorted(ready_by_activity[activity], key=lambda ot: (_aware(order_state[ot[0]]["order"].despatch_due), order_state[ot[0]]["order"].order_ref))
                elig: list[tuple[Worker, float, str]] = []
                for w in available_now:
                    personal = personal_rates.get((w.worker_id, activity))
                    std_seconds = standards.get(activity)
                    standard_rate = 3600 / std_seconds if std_seconds else None
                    try:
                        day_rate = day_rates.get((activity, weekday))
                        rate, source = resolve_activity_rate(personal_rate=personal, role_rate=None, day_rate=day_rate, standard_rate_per_hour=standard_rate, productivity_index=productivity.get(w.worker_id))
                    except ValueError:
                        continue
                    elig.append((w, rate, source))
                if not elig:
                    activity_flags[activity].add("missing_skill")
                    missing_evidence.append(f"no eligible worker for activity '{activity}' in the interval starting {sub.start_at.isoformat()}")
                    continue

                equipment_id = next((s.get("equipment_id") for _o, s in tasks if s.get("equipment_id")), None)
                hc = headcount_limits.get((activity, instance.shift_code), headcount_limits.get((activity, None)))
                max_people = hc[1] if hc else len(elig)
                min_people = hc[0] if hc else 0
                if equipment_id:
                    if equipment_id not in equipment_pools:
                        missing_evidence.append(f"activity '{activity}' needs equipment '{equipment_id}' which is not configured at site '{site_id}'")
                        equip_cap = 0
                    else:
                        # Shared across every activity drawing on this pool in this sub-interval —
                        # a second activity sees what the first already used, not the full pool
                        # again (priority 10: "shared equipment capacity across overlapping activities").
                        equip_cap = max(0, equipment_remaining.get(equipment_id, 0))
                else:
                    equip_cap = len(elig)
                available_worker_count = max(0, min(len(elig), max_people, equip_cap))
                if equipment_id and equip_cap < len(elig) and equip_cap <= max_people:
                    activity_flags[activity].add("no_equipment")
                elif max_people < len(elig):
                    activity_flags[activity].add("headcount_cap")

                # Employment-type fill priority picks WHO is assigned first when capacity is
                # constrained; rate (desc) breaks ties within the same priority (priority 3).
                elig_sorted = sorted(elig, key=lambda x: (fill_priority_key(fill_priorities, scope="employment_type", value=x[0].employment_type), -x[1], x[0].worker_id))
                assigned = elig_sorted[:available_worker_count]
                if assigned:
                    any_assignment_made = True
                if equipment_id and assigned:
                    equipment_remaining[equipment_id] = equipment_remaining.get(equipment_id, 0) - len(assigned)
                if assigned and len(assigned) < min_people:
                    headcount_violations.append({"activity": activity, "interval_start": sub.start_at.isoformat(), "assigned": len(assigned), "min_headcount": min_people})
                for w, _r, _s in assigned:
                    available_now.remove(w)
                if not assigned:
                    activity_flags[activity].add("insufficient_people")
                    missing_evidence.append(f"no capacity available for activity '{activity}' in the interval starting {sub.start_at.isoformat()}")
                    continue

                congestion = resolve_productivity_loss(congestion_rules, loss_type="congestion", site_id=site_id, activity=activity, weekday=weekday, shift_code=instance.shift_code)
                off_task = resolve_productivity_loss(offtask_rules, loss_type="off_task", site_id=site_id, activity=activity, weekday=weekday, shift_code=instance.shift_code)
                try:
                    absenteeism = resolve_absenteeism(absenteeism_rules, site_id=site_id, activity=activity, weekday=weekday, shift_code=instance.shift_code or "")
                except AmbiguousAbsenteeismRule as exc:
                    absenteeism = None
                    missing_evidence.append(str(exc))

                offered_hours = sub.productive_hours
                if off_task:
                    # off_task_hours is a flat reduction for the WHOLE shift, not per sub-interval —
                    # prorate by this sub's share of the shift's wall-clock span so splitting a shift
                    # into finer scheduling intervals never deducts it more than once in total.
                    shift_span_hours = (instance.end_at - instance.start_at).total_seconds() / 3600
                    sub_span_hours = (sub.end_at - sub.start_at).total_seconds() / 3600
                    prorated_off_task = off_task.off_task_hours * (sub_span_hours / shift_span_hours) if shift_span_hours > 0 else 0.0
                    offered_hours = apply_off_task_hours(offered_hours, prorated_off_task)
                # Capacity actually consumable THIS sub-interval is also bounded by the ready tasks'
                # own release/despatch_due window — a sub-interval wider than an order's remaining
                # deadline must not hand it more throughput than that deadline allows.
                clip_end = min(sub.end_at, min(_aware(order_state[o]["order"].despatch_due) for o, _s in tasks))
                clip_start = max(sub.start_at, max(s["release_at"] for _o, s in tasks))
                capacity_hours = max(0.0, min(offered_hours, (clip_end - clip_start).total_seconds() / 3600)) if clip_end > clip_start else 0.0

                total_rate = sum(apply_congestion(rate, congestion.percent_loss) if congestion else rate for _w, rate, _s in assigned)
                if absenteeism:
                    total_rate *= (1 - absenteeism.absence_pct)
                capacity_units = total_rate * capacity_hours

                for w, _rate, _source in assigned:
                    cr = resolve_cost_rate(cost_rules, labour_type=w.employment_type, role=activity, position_grade=w.position_grade, provider_id=w.provider_id)
                    total_paid_hours += sub.paid_hours
                    total_productive_hours += offered_hours
                    if cr is None:
                        uncosted_paid_hours += sub.paid_hours
                        missing_evidence.append(f"no cost rate configured for '{w.employment_type}'/'{activity}' — cost is incomplete")
                    else:
                        total_cost += _cost_for(w, sub.paid_hours, cr.rate, sub.start_at)
                    worker_busy_until[w.worker_id] = sub.end_at
                    if equipment_id:
                        equipment_events.append(EquipmentAssignment(assignment_ref=f"{w.worker_id}@{sub.start_at.isoformat()}", equipment_id=equipment_id, start_at=sub.start_at, end_at=sub.end_at))

                remaining_units = capacity_units
                for order_id, step in tasks:
                    if remaining_units <= 1e-9 or step["remaining"] <= 1e-9:
                        continue
                    take = min(step["remaining"], remaining_units)
                    zone_id = step.get("zone_id")
                    if zone_id and take >= step["remaining"] - 1e-9:
                        cap_info = staging_capacity.get(zone_id)
                        if cap_info and cap_info[1] == order_state[order_id]["order"].unit:
                            room = max(0.0, cap_info[0] - current_occupancy.get(zone_id, 0.0))
                            if take > room + 1e-9:
                                staging_delays.append({"order_ref": order_state[order_id]["order"].order_ref, "zone_id": zone_id, "at": sub.start_at.isoformat(), "held_back_quantity": round(take - room, 3)})
                                continue  # upstream work is delayed by the full zone, not forced to overflow it
                    if step["started_at"] is None:
                        step["started_at"] = clip_start
                    hours_fraction = (take / total_rate) if total_rate > 0 else 0.0
                    step["remaining"] -= take
                    remaining_units -= take
                    step["hours"] += hours_fraction
                    if step["remaining"] <= 1e-9:
                        # Cumulative hours consumed, counted from when this step FIRST received any
                        # capacity — not from whichever sub-interval happens to finish it — so a step
                        # spanning several scheduling intervals reports a sane completion time.
                        completed_at = step["started_at"] + timedelta(hours=step["hours"])
                        step["completed_at"] = completed_at
                        steps_list = order_state[order_id]["steps"]
                        idx = steps_list.index(step)
                        if idx + 1 < len(steps_list):
                            steps_list[idx + 1]["release_at"] = completed_at + timedelta(minutes=steps_list[idx + 1]["lag_minutes"])
                        if zone_id:
                            current_occupancy[zone_id] = current_occupancy.get(zone_id, 0.0) + take
                            staging_events[zone_id].append(StagingMovementCalc(occurred_at=completed_at, movement_type="arrival", quantity=take, unit=order_state[order_id]["order"].unit))

    # --- equipment safety net (catches overlap across non-adjacent intervals/shift codes) -------------------------
    equipment_violations = check_equipment_capacity(equipment_events, pools=equipment_pools) if equipment_events else []

    # --- staging capacity --------------------------------------------------------------------------------------
    staging_results: dict[str, dict] = {}
    for zone_id, events in staging_events.items():
        cap = staging_capacity.get(zone_id)
        if cap is None:
            staging_results[zone_id] = {"available": False, "reason": "no staging capacity configured for this zone — staging unavailable for this run"}
            continue
        capacity, unit = cap
        try:
            points = compute_staging_occupancy(events, capacity_unit=unit)
        except StagingUnitMismatch as exc:
            staging_results[zone_id] = {"available": False, "reason": str(exc)}
            continue
        violations = check_staging_capacity(points, capacity)
        staging_results[zone_id] = {"available": True, "capacity": capacity, "unit": unit, "peak_occupancy": round(max((p.occupancy for p in points), default=0.0), 3),
                                    "violations": [{"at": v.at.isoformat(), "occupancy": round(v.occupancy, 3)} for v in violations]}

    # --- assemble per-order results -----------------------------------------------------------------------------
    order_results: list[dict] = []
    total_shortfall = total_quantity = total_produced = 0.0
    for order_id, state in order_state.items():
        order = state["order"]
        total_quantity += state["quantity"]
        step_rows = []
        shortfall = 0.0
        for s in state["steps"]:
            shortfall += s["remaining"]
            reason = None
            if s["remaining"] > 1e-9:
                flags = activity_flags.get(s["activity"], set())
                reason = ("missing_skill" if "missing_skill" in flags else "no_equipment" if "no_equipment" in flags else
                          "headcount_cap" if "headcount_cap" in flags else "deadline_breach")
            function, flow = standard_function_flow.get(s["activity"], (None, None))
            step_rows.append({"sequence": s["sequence"], "activity": s["activity"], "function": function, "flow": flow, "release_at": s["release_at"].isoformat() if s["release_at"] else None,
                              "completed_at": s["completed_at"].isoformat() if s["completed_at"] else None, "shortfall_quantity": round(s["remaining"], 3), "shortfall_reason": reason})
        total_shortfall += shortfall
        total_produced += state["quantity"] - shortfall
        order_results.append({"order_ref": order.order_ref, "source": state.get("source", "order"), "despatch_due": order.despatch_due.isoformat(), "quantity": round(state["quantity"], 3),
                              "steps": step_rows, "on_time": shortfall <= 1e-9, "shortfall_quantity": round(shortfall, 3)})

    # "No plan found" (proven infeasibility — the scheduler never managed to put a single worker on
    # anything, direct or indirect) is distinct from "attempted and constrained to zero direct
    # output" — the latter is already explained by indirect_coverage_gaps / headcount_violations /
    # staging_delays / missing_evidence and stays a normal feasible_with_slack result. Only the
    # former is a failed run with a reason (priority 1) instead of a silently empty "success".
    if total_quantity > 1e-9 and total_produced <= 1e-9 and not any_assignment_made:
        raise SolverInfeasible(f"no feasible allocation found for any of {len(order_state)} order/demand line(s) at site '{site_id}' within the planning window — "
                               "no worker could be assigned to anything at all (check shifts, eligible workers, equipment and headcount limits)")

    coverage = 1.0 if total_quantity == 0 else max(0.0, 1 - total_shortfall / total_quantity)
    feasibility = "feasible"
    if total_shortfall > 0 or indirect_gaps or headcount_violations or equipment_violations or staging_delays or any(not s["available"] or s["violations"] for s in staging_results.values()):
        feasibility = "feasible_with_slack"

    return SolverOutcome(
        result={
            "orders": order_results,
            "demand_mode": demand_mode, "forecast_basis": forecast_basis if demand_mode == "hybrid" else None,
            "indirect_coverage_gaps": indirect_gaps,
            "headcount_violations": headcount_violations,
            "equipment_violations": [{"equipment_id": v.equipment_id, "at": v.at.isoformat(), "concurrent": v.concurrent, "quantity_available": v.quantity_available} for v in equipment_violations],
            "staging": staging_results,
            "staging_delays": staging_delays,
            "kpis": {
                "orders_planned": len(order_results), "total_shortfall_quantity": round(total_shortfall, 3), "coverage_pct": round(coverage * 100, 2),
                "total_paid_hours": round(total_paid_hours, 3), "total_productive_hours": round(total_productive_hours, 3), "indirect_paid_hours": round(indirect_paid_hours, 3),
                "total_cost": round(total_cost, 2) if uncosted_paid_hours == 0 else None, "uncosted_paid_hours": round(uncosted_paid_hours, 3),
            },
        },
        baseline={"method": "order_driven", "orders_in_window": len(orders), "demand_lines": len(order_state)},
        proposed={"method": "order_driven_shared_schedule", "orders_planned": len(order_results), "shift_instances": len(instances), "scheduling_interval_minutes": SCHEDULING_INTERVAL_MINUTES},
        delta={"orders_shortfall": sum(1 for r in order_results if not r["on_time"])},
        confidence_components=ConfidenceComponents(
            completeness=1.0 if not missing_evidence else round(len(order_results) / max(len(order_state), 1), 4),
            freshness=1.0, mapping_quality=1.0, forecast_validation=1.0, constraint_coverage=1.0,
            solution_quality=1.0 if total_shortfall == 0 else 0.5,
        ),
        primary_drivers=[f"Planned {len(order_results)} demand line(s) under '{demand_mode}'; {round(total_shortfall, 1)} unit(s) shortfall" if total_shortfall else f"Planned {len(order_results)} demand line(s) under '{demand_mode}' fully on time"],
        missing_evidence=missing_evidence,
        assumptions=["customer-scoped fill priority is rejected at import, not silently inert — only activity and employment_type scopes are consulted here",
                    "equipment/zone requirements are read per process step and assumed uniform for a given activity name within one interval",
                    "a hybrid run's forecast/known-order split uses local-calendar-day buckets; a different forecast granularity is approximated to the day"],
        feasibility=feasibility,
    )
