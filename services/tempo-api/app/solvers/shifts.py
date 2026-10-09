"""Shift calendar: configurable per policy, localised to the site's IANA timezone.

The calendar lives in the policy constraints (`shift_calendar`), so a tenant configures it
instead of inheriting a fixed two-shift UTC day. Times are wall-clock hours in the planning
window's timezone. A shift whose end hour is <= its start hour is overnight (it ends the next
calendar day). Start/end instants are computed by localising wall-clock times, so a shift on a
daylight-saving change day keeps its wall-clock start and its true UTC duration may be 1h
longer/shorter than the nominal `hours`; the roster reports nominal paid hours (explicit rule:
pay follows the nominal length unless a tenant policy says otherwise).

`DEFAULT_SHIFT_CALENDAR` is the pre-existing two-shift day, kept only as the fallback for a
tenant that has not configured one; a production tenant must configure its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class ShiftDefinition:
    code: str
    start_hour: int
    end_hour: int
    # Optional share of the day's headcount this shift receives (tenant-configured; all shifts or none).
    share: float | None = None

    @property
    def hours(self) -> int:
        span = (self.end_hour - self.start_hour) % 24
        return span or 24

    @property
    def overnight(self) -> bool:
        return self.end_hour <= self.start_hour


DEFAULT_SHIFT_CALENDAR: list[ShiftDefinition] = [
    ShiftDefinition(code="day", start_hour=6, end_hour=14),
    ShiftDefinition(code="night", start_hour=14, end_hour=22),
]
# Backwards-compatible alias.
SHIFT_CALENDAR = DEFAULT_SHIFT_CALENDAR


def calendar_from_constraints(constraints: dict[str, Any]) -> list[ShiftDefinition]:
    raw = constraints.get("shift_calendar")
    if not raw:
        return list(DEFAULT_SHIFT_CALENDAR)
    calendar = [ShiftDefinition(code=str(s["code"]), start_hour=int(s["start_hour"]), end_hour=int(s["end_hour"]),
                                share=(float(s["share"]) if s.get("share") is not None else None)) for s in raw]
    shares = [s.share for s in calendar]
    if any(x is not None for x in shares):
        if any(x is None for x in shares) or any(x < 0 for x in shares) or abs(sum(shares) - 1.0) > 1e-6:
            raise ValueError("shift_calendar shares must be given for every shift, be non-negative and sum to 1")
    if len({s.code for s in calendar}) != len(calendar):
        raise ValueError("shift_calendar codes must be unique")
    for s in calendar:
        if not (0 <= s.start_hour < 24 and 0 <= s.end_hour <= 24):
            raise ValueError("shift_calendar hours must be 0-23 (end may be 24)")
    return calendar


def shift_bounds_utc(day_iso: str, shift: ShiftDefinition, tz_name: str) -> tuple[datetime, datetime]:
    """UTC start/end of `shift` on the local calendar date `day_iso` in `tz_name`."""
    tz = ZoneInfo(tz_name)
    day = datetime.fromisoformat(day_iso[:10])
    start_local = datetime(day.year, day.month, day.day, shift.start_hour % 24, tzinfo=tz)
    end_naive = datetime(day.year, day.month, day.day, shift.start_hour % 24) + timedelta(hours=shift.hours)
    end_local = end_naive.replace(tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def hhmm_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def shift_elapsed_minutes(start_time: str, end_time: str) -> int:
    """Minutes from start_time to end_time, crossing midnight when end <= start (equal start/end means a
    full 24-hour shift, matching `ShiftDefinition.hours`)."""
    span = (hhmm_to_minutes(end_time) - hhmm_to_minutes(start_time)) % 1440
    return span or 1440


@dataclass(frozen=True)
class BreakDefinition:
    starts_after_minutes: int
    duration_minutes: int
    is_paid: bool


def shift_hours(elapsed_minutes: int, breaks: list[BreakDefinition]) -> dict[str, float]:
    """Elapsed/paid/productive hours for a shift (brief Appendix C): paid time excludes unpaid breaks;
    productive time additionally excludes paid breaks. Paid breaks still cost money (paid_hours reflects
    that), but no break counts as working time."""
    unpaid_minutes = sum(b.duration_minutes for b in breaks if not b.is_paid)
    all_break_minutes = sum(b.duration_minutes for b in breaks)
    return {
        "elapsed_hours": elapsed_minutes / 60,
        "paid_hours": (elapsed_minutes - unpaid_minutes) / 60,
        "productive_hours": (elapsed_minutes - all_break_minutes) / 60,
    }


def split_headcount(total: int, calendar: list[ShiftDefinition]) -> dict[str, int]:
    """Allocate a day's headcount across shifts: by configured share (largest-remainder rounding) or, with no
    shares configured, evenly (the original behaviour)."""
    codes = [s.code for s in calendar]
    if all(s.share is not None for s in calendar):
        raw = {s.code: total * s.share for s in calendar}
        out = {c: int(raw[c]) for c in codes}
        for c in sorted(codes, key=lambda c: raw[c] - out[c], reverse=True)[: total - sum(out.values())]:
            out[c] += 1
        return out
    base, remainder = divmod(total, len(codes))
    return {c: base + (1 if i < remainder else 0) for i, c in enumerate(codes)}
