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
    # Leave & RDO Planning (§3.7) — same class of gap: no canonical entity
    # prices staffing-gap risk or approval dissatisfaction, so these are
    # flat, tenant-overridable defaults.
    "leave_shortage_penalty_per_worker": 300.0,
    "leave_rejection_penalty": 150.0,
    # Intraday Reallocation (§3.5) — flat move cost/productivity/risk
    # defaults; no canonical entity prices zone-to-zone movement or models
    # per-worker-per-zone productivity yet (same gap as workforce_mix's
    # productivity-fixed-at-1.0 simplification).
    "intraday_move_cost": 15.0,
    "intraday_backlog_risk_per_unit": 40.0,
    # Team Composition (§3.8) — no canonical entity carries per-worker
    # productivity/quality/reliability ratings yet (WorkerPerformanceProfile
    # is a Tempo-governed addition, same tier as ActivityRoleZoneMap); a
    # worker with no profile row is assumed exactly average. Deviation
    # weights convert the model's abstract prod/qual/reliability units into
    # the same dollar scale as CostTarget so all four objective terms are
    # comparable — same role as named_roster's fairness_weight.
    "default_productivity_index": 1.0,
    "default_quality_index": 1.0,
    "default_reliability_index": 1.0,
    "team_internal_min_ratio": 0.5,
    "team_mentor_min_ratio": 0.1,
    "team_prod_deviation_weight": 200.0,
    "team_qual_deviation_weight": 200.0,
    "team_reliability_weight": 50.0,
    # 3PL Cost-to-Serve & Margin (§3.9) — SellRateContract/LabourCostRule
    # cover most of the model, but a customer/activity with no contract row,
    # or overhead allocation, still needs a flat tenant-overridable default
    # (same gap as default_rate above).
    "margin_default_sell_rate": 60.0,
    "margin_default_sla_penalty_per_unit": 20.0,
    "margin_overhead_rate_per_hour": 5.0,
    # Robust / Scenario Optimisation (§3.10, Monte Carlo) — scenario
    # generation parameters; no canonical entity models demand volatility,
    # absenteeism or productivity drift distributions yet, so these are flat
    # tenant-overridable defaults, same class of gap as the others above.
    # scenario_random_seed makes runs reproducible/auditable (Integration
    # Spec run immutability) rather than genuinely random each time.
    "scenario_count": 200,
    "scenario_random_seed": 42,
    "scenario_demand_volatility_cv": 0.15,
    "scenario_absenteeism_rate_mean": 0.05,
    "scenario_absenteeism_rate_std": 0.03,
    "scenario_productivity_drift_std": 0.1,
    # Controlled Action (§12) — how long a completed run's recommendation
    # stays actionable, and how long a validated action_token stays valid
    # for execution. No canonical entity prices either; flat tenant-
    # overridable defaults, same class of gap as default_rate above.
    "recommendation_ttl_seconds": 3600,
    "action_token_ttl_seconds": 300,
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
