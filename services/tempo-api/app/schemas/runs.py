"""Run lifecycle, explanation and error contracts — §8, §10, §11, Appendix B/C."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Appendix C — core enumerations
RunType = Literal[
    "demand_forecast",
    "labour_requirement",
    "workforce_mix",
    "named_roster",
    "intraday_reallocation",
    "training_coverage",
    "leave_rdo",
    "team_composition",
    "margin_3pl",
    "scenario",
]
ObjectiveProfile = Literal["lowest_cost", "best_service", "balanced", "lowest_risk", "custom_policy"]
ConfidenceBand = Literal["high", "medium", "low", "insufficient_evidence"]
Feasibility = Literal["feasible", "feasible_with_slack", "infeasible"]
RunStatus = Literal[
    "accepted",
    "validating",
    "queued",
    "running",
    "cancel_requested",
    "completed",
    "completed_with_warnings",
    "failed",
    "cancelled",
    "expired",
]

# §8's Phase 0/A run types — the rest of Appendix C's run_type values are legal
# enum members but return TEMPO-RUN-004 (not yet implemented) until their phase
# lands; see docs/roadmap.md.
IMPLEMENTED_RUN_TYPES: set[str] = {"demand_forecast", "labour_requirement", "workforce_mix", "named_roster"}


class Money(BaseModel):
    amount: str  # decimal-as-string per §8.1 money convention — never float
    currency: str


class RunScope(BaseModel):
    tenant_id: str
    site_ids: list[str] = Field(default_factory=list)
    customer_ids: list[str] = Field(default_factory=list)


class PlanningWindow(BaseModel):
    start: datetime
    end: datetime
    timezone: str
    bucket_minutes: int = 60


class RunInput(BaseModel):
    snapshot_mode: Literal["latest_accepted", "pinned"] = "latest_accepted"
    demand_forecast_run_id: str | None = None


class RunConfiguration(BaseModel):
    policy_version: str | None = None
    model_version: str | None = None
    objective_profile: ObjectiveProfile = "balanced"


class RunOptions(BaseModel):
    alternatives: list[str] = Field(default_factory=list)
    explainability: Literal["full", "summary"] = "full"


class RunRequest(BaseModel):
    """§8.3 common run request."""

    request_id: str
    scope: RunScope
    planning_window: PlanningWindow
    input: RunInput = Field(default_factory=RunInput)
    configuration: RunConfiguration = Field(default_factory=RunConfiguration)
    options: RunOptions = Field(default_factory=RunOptions)


class RunLinks(BaseModel):
    self_: str = Field(alias="self")
    cancel: str

    model_config = {"populate_by_name": True}


class RunResponse(BaseModel):
    """§8.4 run creation response (202 Accepted)."""

    run_id: str
    run_type: RunType
    status: RunStatus
    created_at: datetime
    links: RunLinks
    input_snapshot_id: str
    effective_scope: RunScope
    warnings: list[str] = Field(default_factory=list)


class ConfidenceComponents(BaseModel):
    completeness: float
    freshness: float
    mapping_quality: float
    forecast_validation: float
    constraint_coverage: float
    solution_quality: float


class Confidence(BaseModel):
    """§11.2 — computed from disclosed components, never a raw LLM score."""

    score: float
    band: ConfidenceBand
    method: str
    components: ConfidenceComponents
    reasons: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    """§11.1 shared explanation contract — every field here is mandatory
    per the spec; callers should treat a missing field as a contract bug,
    not an optional extra.
    """

    baseline: dict[str, Any]
    proposed: dict[str, Any]
    delta: dict[str, Any]
    dollar_value: Money | None = None
    confidence: Confidence
    primary_drivers: list[str]
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    data_lineage: dict[str, Any]
    freshness: dict[str, Any]
    missing_evidence: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    feasibility: Feasibility
    evidence_ref: str


class ModelInfo(BaseModel):
    name: str
    version: str
    solver: str


class CompletedRunResult(BaseModel):
    """§8.5 completed result contract."""

    run_id: str
    status: RunStatus
    model: ModelInfo
    result: dict[str, Any]
    explanation: Explanation
    lineage: dict[str, Any]
    completed_at: datetime
    supersedes_run_id: str | None = None


class ProblemDetail(BaseModel):
    """§8.6 — RFC 9457-style problem details."""

    type: str
    title: str
    status: int
    detail: str
    instance: str
    error_code: str
    correlation_id: str | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    retryable: bool = False
