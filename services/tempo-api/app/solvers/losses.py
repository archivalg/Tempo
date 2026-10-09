"""Congestion/off-task loss, staging capacity, and grade-aware costing (order-driven-planning
Stage 4). Pure functions — not yet wired into order_workload.py's per-order scheduling. See
docs/order-driven-planning.md for what remains open.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def apply_congestion(rate_per_hour: float, percent_loss: float) -> float:
    """An explicit, flat rate reduction — never an inferred crowding curve."""
    if not 0 <= percent_loss < 1:
        raise ValueError("percent_loss must be in [0, 1)")
    return rate_per_hour * (1 - percent_loss)


def apply_off_task_hours(available_hours: float, off_task_hours: float) -> float:
    """An explicit capacity reduction in hours, applied once — breaks are already excluded from
    `available_hours` upstream (app.solvers.shifts.shift_hours), so this must never also subtract
    break time, and off-task hours must never be deducted twice across both a congestion rate cut
    and an hours cut for the same cause."""
    if off_task_hours < 0:
        raise ValueError("off_task_hours cannot be negative")
    return max(0.0, available_hours - off_task_hours)


@dataclass(frozen=True)
class StagingMovement:
    occurred_at: datetime
    movement_type: str  # initial | arrival | departure
    quantity: float
    unit: str


@dataclass(frozen=True)
class StagingOccupancyPoint:
    at: datetime
    occupancy: float


class StagingUnitMismatch(ValueError):
    pass


def compute_staging_occupancy(movements: list[StagingMovement], *, capacity_unit: str) -> list[StagingOccupancyPoint]:
    """Running occupancy after each movement, in capacity order. A movement in a different unit than
    the zone's capacity is rejected outright — never silently converted with an invented ratio."""
    for m in movements:
        if m.unit != capacity_unit:
            raise StagingUnitMismatch(f"movement unit '{m.unit}' does not match the zone's capacity unit '{capacity_unit}' — add a conversion or correct the upload before capacity can be validated")
    ordered = sorted(movements, key=lambda m: (m.occurred_at, m.movement_type != "initial"))
    occupancy = 0.0
    points: list[StagingOccupancyPoint] = []
    for m in ordered:
        occupancy += m.quantity if m.movement_type in ("initial", "arrival") else -m.quantity
        points.append(StagingOccupancyPoint(at=m.occurred_at, occupancy=occupancy))
    return points


def check_staging_capacity(points: list[StagingOccupancyPoint], capacity: float) -> list[StagingOccupancyPoint]:
    return [p for p in points if p.occupancy > capacity]


@dataclass(frozen=True)
class CostRule:
    labour_type: str
    role: str
    rate: float
    position_grade: str | None = None
    provider_id: str | None = None
    overtime_multiplier: float | None = None
    surcharge: float | None = None
    currency: str = "AUD"


@dataclass(frozen=True)
class ResolvedCost:
    rate: float
    currency: str
    overtime_multiplier: float | None
    surcharge: float | None
    matched_grade: bool
    matched_provider: bool


def resolve_cost_rate(rules: list[CostRule], *, labour_type: str, role: str, position_grade: str | None = None, provider_id: str | None = None) -> ResolvedCost | None:
    """Most specific match wins: grade+provider > grade > provider > (labour_type, role) alone.
    Award/position names are identifiers here, not an award-compliance calculation — this only
    selects a configured rate, never derives one. Returns None when no rate is configured, so the
    caller can show cost as unavailable rather than zero."""
    candidates = [r for r in rules if r.labour_type == labour_type and r.role == role
                  and (r.position_grade is None or r.position_grade == position_grade)
                  and (r.provider_id is None or r.provider_id == provider_id)]
    if not candidates:
        return None

    def specificity(r: CostRule) -> int:
        return (1 if r.position_grade is not None else 0) + (1 if r.provider_id is not None else 0)

    best = max(candidates, key=specificity)
    return ResolvedCost(rate=best.rate, currency=best.currency, overtime_multiplier=best.overtime_multiplier, surcharge=best.surcharge,
                         matched_grade=best.position_grade is not None, matched_provider=best.provider_id is not None)


def labour_cost(*, paid_hours: float, rate_per_hour: float, overtime_hours: float = 0.0, overtime_multiplier: float = 1.0) -> float:
    """Paid breaks are part of `paid_hours` (app.solvers.shifts.shift_hours already excludes only
    unpaid breaks from it), so they are costed; unpaid breaks were never in `paid_hours` to begin
    with, so they are not."""
    straight_hours = max(0.0, paid_hours - overtime_hours)
    return round(straight_hours * rate_per_hour + overtime_hours * rate_per_hour * overtime_multiplier, 2)
