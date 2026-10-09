"""Common solver output shape so app/api/v1/runs.py can assemble the
§11.1 explanation contract identically regardless of which model ran.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.runs import ConfidenceComponents


@dataclass
class SolverOutcome:
    result: dict[str, Any]
    baseline: dict[str, Any]
    proposed: dict[str, Any]
    delta: dict[str, Any]
    confidence_components: ConfidenceComponents
    primary_drivers: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    feasibility: str = "feasible"
    dollar_value: dict[str, str] | None = None
    source_systems: list[str] = field(default_factory=lambda: ["tempo_native"])


class InsufficientData(Exception):
    """Raised when a solver has no usable canonical input at all — maps to
    TEMPO-DATA-004 (§8.6) rather than proceeding with an empty result.
    Never persists a run row: the request never produced anything worth
    auditing as an attempted plan.
    """


class SolverInfeasible(Exception):
    """Raised when a solver genuinely attempted to solve (CBC/CP-SAT or
    equivalent returned a non-OPTIMAL/FEASIBLE status) and concluded no
    assignment satisfies the hard constraints — distinct from
    InsufficientData, which means there was nothing to attempt at all.
    Unlike InsufficientData, this DOES persist a terminal run (status
    "failed", Feasibility "infeasible") so a genuinely infeasible run is
    never indistinguishable from one that never happened (order-driven-
    planning Stage 0 finding: both previously collapsed into the same
    rolled-back, unrecorded outcome)."""
