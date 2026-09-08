"""Governed policy resolution — OD-08, generalized beyond confidence weights
to the mix/roster policy constants flagged in services/tempo-api/README.md
("Internal-min / hire-max ratios and the shortfall penalty are hardcoded
defaults, not sourced from OptimisationPolicy yet").

Pattern: versioned code defaults + an admin-override slot, not bare module
constants. A tenant with no configured policy gets DEFAULT_POLICY_VERSION's
values; a stored OptimisationPolicy row for that tenant overrides individual
keys — a partial override merges over the defaults rather than replacing
them wholesale, so a tenant can tune one ratio without having to restate
every constant. (This shape was checked against a sibling Prime AI system's
confidence-scoring engine, which uses the same versioned-defaults-plus-
admin-override structure — see docs/roadmap.md.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import OptimisationPolicy

DEFAULT_POLICY_VERSION = "default-1.0"

DEFAULT_CONSTRAINTS: dict[str, Any] = {
    "hours_per_worker_per_day": 8.0,
    "max_overtime_hours_per_worker_per_day": 2.0,
    "internal_min_ratio": 0.6,
    "hire_max_ratio": 0.4,
    "default_rate": 40.0,
    "default_overtime_multiplier": 1.5,
    "default_hire_surcharge": 8.0,
    "sla_penalty_per_hour": 250.0,
    "max_consecutive_days": 6,
    "fairness_weight": 50.0,
    "preference_weight": 20.0,
    "shortfall_penalty_per_hour": 250.0,
    # Training & Certification Coverage (§3.6) — no canonical entity prices
    # an actual training program yet, so these are flat, tenant-overridable
    # stand-ins, the same kind of gap as default_rate above.
    "training_cost_per_certification": 500.0,
    "training_benefit_per_certification_per_period": 50.0,
    "training_shortage_penalty_per_worker": 300.0,
    "training_budget": None,  # None = unconstrained
}

DEFAULT_WEIGHTS: dict[str, float] = {
    "completeness": 0.2,
    "freshness": 0.15,
    "mapping_quality": 0.15,
    "forecast_validation": 0.2,
    "constraint_coverage": 0.15,
    "solution_quality": 0.15,
}

DEFAULT_TOLERANCES: dict[str, Any] = {}


@dataclass
class ResolvedPolicy:
    policy_version: str
    constraints: dict[str, Any]
    weights: dict[str, float]
    tolerances: dict[str, Any]


def resolve_policy(db: Session, tenant_id: str, requested_policy_version: str | None = None) -> ResolvedPolicy:
    row: OptimisationPolicy | None = None
    if requested_policy_version:
        candidate = db.get(OptimisationPolicy, requested_policy_version)
        if candidate is not None and candidate.tenant_id == tenant_id:
            row = candidate
        # A requested version that doesn't exist, or belongs to another
        # tenant, falls through to the tenant's latest policy below rather
        # than silently using someone else's constraints.

    if row is None:
        row = db.scalar(
            select(OptimisationPolicy)
            .where(OptimisationPolicy.tenant_id == tenant_id)
            .order_by(OptimisationPolicy.created_at.desc())
            .limit(1)
        )

    if row is None:
        return ResolvedPolicy(
            policy_version=DEFAULT_POLICY_VERSION,
            constraints=dict(DEFAULT_CONSTRAINTS),
            weights=dict(DEFAULT_WEIGHTS),
            tolerances=dict(DEFAULT_TOLERANCES),
        )

    return ResolvedPolicy(
        policy_version=row.policy_version,
        constraints={**DEFAULT_CONSTRAINTS, **(row.constraints or {})},
        weights={**DEFAULT_WEIGHTS, **(row.weights or {})},
        tolerances={**DEFAULT_TOLERANCES, **(row.tolerances or {})},
    )
