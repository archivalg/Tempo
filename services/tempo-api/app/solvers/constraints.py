"""Operational constraint calculations (order-driven-planning Stage 3): fill priorities, absenteeism,
equipment pools, headcount limits. Pure functions — not yet wired into order_workload.py's per-order
scheduling (see docs/order-driven-planning.md for what remains open).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AbsenteeismRule:
    site_id: str
    activity: str | None
    weekday: str | None
    shift_code: str | None
    absence_pct: float

    @property
    def specificity(self) -> int:
        return sum(1 for f in (self.activity, self.weekday, self.shift_code) if f is not None)


class AmbiguousAbsenteeismRule(ValueError):
    pass


def resolve_absenteeism(rules: list[AbsenteeismRule], *, site_id: str, activity: str, weekday: str, shift_code: str) -> AbsenteeismRule | None:
    """Most specific (activity + weekday + shift_code) match wins; a broader rule is used only when
    no more specific one matches. Two rules tied on specificity for the same scope are ambiguous and
    must be rejected rather than silently picking one."""
    candidates = [r for r in rules if r.site_id == site_id and (r.activity is None or r.activity == activity)
                  and (r.weekday is None or r.weekday == weekday) and (r.shift_code is None or r.shift_code == shift_code)]
    if not candidates:
        return None
    best = max(c.specificity for c in candidates)
    tied = [c for c in candidates if c.specificity == best]
    if len(tied) > 1:
        raise AmbiguousAbsenteeismRule(f"{len(tied)} equally-specific absenteeism rules match site '{site_id}' activity '{activity}' weekday '{weekday}' shift '{shift_code}'")
    return tied[0]


def scheduled_hours_for_absenteeism(productive_hours: float, absence_pct: float) -> float:
    """Brief: "scheduled hours = H/(1-a)" — a 10% absence rate needs 11.11% extra capacity. Applied
    once; never stack this with a separate headcount buffer or a scenario's own absenteeism draw."""
    if not 0 <= absence_pct < 1:
        raise ValueError("absence_pct must be in [0, 1)")
    return productive_hours / (1 - absence_pct)


@dataclass(frozen=True)
class EquipmentAssignment:
    assignment_ref: str
    equipment_id: str
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class EquipmentViolation:
    equipment_id: str
    at: datetime
    concurrent: int
    quantity_available: int
    assignment_refs: tuple[str, ...]


def check_equipment_capacity(assignments: list[EquipmentAssignment], pools: dict[str, int]) -> list[EquipmentViolation]:
    """Sweep-line check: flags every instant concurrent usage of a pool exceeds what's available,
    including assignments on overlapping shifts that never show up in the same single shift."""
    violations: list[EquipmentViolation] = []
    by_pool: dict[str, list[EquipmentAssignment]] = {}
    for a in assignments:
        by_pool.setdefault(a.equipment_id, []).append(a)
    for equipment_id, pool_assignments in by_pool.items():
        available = pools.get(equipment_id)
        if available is None:
            continue
        events = sorted({a.start_at for a in pool_assignments} | {a.end_at for a in pool_assignments})
        for t in events[:-1]:
            active = [a for a in pool_assignments if a.start_at <= t < a.end_at]
            if len(active) > available:
                violations.append(EquipmentViolation(equipment_id=equipment_id, at=t, concurrent=len(active), quantity_available=available,
                                                      assignment_refs=tuple(a.assignment_ref for a in active)))
    return violations


class InvalidHeadcountLimit(ValueError):
    pass


def check_headcount_limit(*, assigned: int, min_headcount: int, max_headcount: int) -> str | None:
    """Returns a shortfall/overflow reason, or None if within bounds. Raises if the limit itself is
    configured min > max (brief: "detect minimum greater than maximum")."""
    if min_headcount > max_headcount:
        raise InvalidHeadcountLimit(f"min_headcount ({min_headcount}) exceeds max_headcount ({max_headcount})")
    if assigned < min_headcount:
        return f"below minimum headcount: {assigned} assigned, {min_headcount} required"
    if assigned > max_headcount:
        return f"exceeds maximum headcount: {assigned} assigned, {max_headcount} allowed"
    return None


def fill_priority_key(priorities: dict[tuple[str, str], int], *, scope: str, value: str, default: int = 999) -> int:
    """Sort key for fill order: lower fills first; an unconfigured scope/value falls to the back,
    never silently treated as highest priority."""
    return priorities.get((scope, value), default)
