"""Data readiness contract — §7.3."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DomainStatus = Literal["ready", "partial", "not_ready"]
ReadinessStatus = Literal["ready", "ready_with_warnings", "not_ready"]


class DomainReadiness(BaseModel):
    domain: str
    status: DomainStatus
    freshness_seconds: int | None = None
    coverage: float | None = None
    warning: str | None = None


class DataReadinessResponse(BaseModel):
    status: ReadinessStatus
    score: float
    as_of: datetime
    required_domains: list[DomainReadiness]
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# §4 data requirements summary — the canonical domains each capability reads.
CAPABILITY_REQUIRED_DOMAINS: dict[str, list[str]] = {
    "forecast.demand": ["demand_bucket"],
    "forecast.labour_requirement": ["demand_bucket", "work_standard"],
    "optimize.mix": ["demand_bucket", "worker", "labour_cost_rule"],
    "optimize.roster": ["worker", "availability", "skill_certification"],
}
