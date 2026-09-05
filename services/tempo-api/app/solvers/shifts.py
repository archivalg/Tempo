"""Fixed shift calendar — Phase A simplification.

Neither the Business Spec nor the Integration Spec's canonical model (§6.1)
defines a "shift definition" entity; ShiftAssignment records an assignment's
own start/end but nothing enumerates the shift *types* a site runs. Rather
than invent another canonical table this early, Phase A fixes a two-shift
day. Replace with a per-tenant configured calendar (sourced from
OptimisationPolicy or a dedicated entity) before this goes near a real
customer — tracked in docs/roadmap.md under Phase A follow-ups.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ShiftDefinition:
    code: str
    start_hour: int
    end_hour: int

    @property
    def hours(self) -> float:
        return self.end_hour - self.start_hour


SHIFT_CALENDAR: list[ShiftDefinition] = [
    ShiftDefinition(code="day", start_hour=6, end_hour=14),
    ShiftDefinition(code="night", start_hour=14, end_hour=22),
]
