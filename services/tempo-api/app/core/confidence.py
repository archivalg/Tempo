"""Confidence calculation — §11.2, OD-08.

Rule-based and versioned, never an LLM score (INT-009, OD-08). Default
weights live in app.core.policy (the single source of truth shared with the
mix/roster policy constants) so a tenant's OptimisationPolicy override
applies here too, not just to the solver-level ratios; they are returned
alongside the score for audit precisely so they can be challenged.
"""
from __future__ import annotations

from app.config import settings
from app.core.policy import DEFAULT_WEIGHTS
from app.schemas.runs import Confidence, ConfidenceComponents

BAND_THRESHOLDS: list[tuple[float, str]] = [
    (0.85, "high"),
    (0.65, "medium"),
    (0.4, "low"),
]


def band_for_score(score: float) -> str:
    for threshold, band in BAND_THRESHOLDS:
        if score >= threshold:
            return band
    return "insufficient_evidence"


def compute_confidence(
    components: ConfidenceComponents,
    reasons: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> Confidence:
    weights = weights or DEFAULT_WEIGHTS
    component_values = components.model_dump()
    score = sum(component_values[key] * weight for key, weight in weights.items())
    score = round(min(max(score, 0.0), 1.0), 4)
    return Confidence(
        score=score,
        band=band_for_score(score),
        method=settings.confidence_method,
        components=components,
        reasons=reasons or [],
    )
