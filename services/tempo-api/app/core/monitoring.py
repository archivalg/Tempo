"""Model monitoring — §15.2's "Model operations: Backtest error, drift,
feature/data coverage, solver gap, timeout and version adoption" (Phase F).

Computed entirely from `OptimisationRun` history already stored by every
phase — no new telemetry pipeline, just reading what runs already record
(`explanation.feasibility`, `explanation.confidence.score`,
`result.backtest_mape`, `model_version`). There is no background scheduler
in this codebase (the same disclosed gap `scenario` and
`recommendation.expiring` carry — see docs/roadmap.md), so drift isn't
detected continuously; `check_drift` is called on demand
(`POST /v1/monitoring/models/drift-check`), comparing a run_type's most
recent runs against its older ones within the same tenant.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.events import event_bus
from app.core.policy import resolve_policy
from app.models.runs import OptimisationRun

_TERMINAL_STATUSES = {"completed", "completed_with_warnings", "failed"}


def _confidence_score(run: OptimisationRun) -> float | None:
    if not run.explanation:
        return None
    confidence = run.explanation.get("confidence") or {}
    return confidence.get("score")


def _backtest_mape(run: OptimisationRun) -> float | None:
    if not run.result:
        return None
    return run.result.get("backtest_mape")


def compute_model_monitoring(db: Session, tenant_id: str) -> dict[str, dict[str, Any]]:
    runs = db.scalars(
        select(OptimisationRun)
        .where(OptimisationRun.tenant_id == tenant_id)
        .where(OptimisationRun.status.in_(_TERMINAL_STATUSES))
        .order_by(OptimisationRun.created_at.asc())
    ).all()

    by_run_type: dict[str, list[OptimisationRun]] = defaultdict(list)
    for run in runs:
        by_run_type[run.run_type].append(run)

    metrics: dict[str, dict[str, Any]] = {}
    for run_type, rows in by_run_type.items():
        infeasible = sum(1 for r in rows if r.explanation and r.explanation.get("feasibility") == "infeasible")
        failed = sum(1 for r in rows if r.status == "failed")
        confidences = [c for c in (_confidence_score(r) for r in rows) if c is not None]
        mapes = [m for m in (_backtest_mape(r) for r in rows) if m is not None]
        version_adoption = Counter(r.model_version for r in rows if r.model_version)

        metrics[run_type] = {
            "run_count": len(rows),
            "solver_gap_rate": round(infeasible / len(rows), 4),
            "failure_rate": round(failed / len(rows), 4),
            "avg_confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
            "avg_backtest_mape": round(sum(mapes) / len(mapes), 4) if mapes else None,
            "model_version_adoption": dict(version_adoption),
        }
    return metrics


def check_drift(db: Session, tenant_id: str) -> list[dict[str, Any]]:
    """Splits each run_type's runs into an older and a more recent half
    (oldest-first order) and flags drift when the recent half's average
    confidence dropped, or its average backtest MAPE rose, beyond policy
    thresholds. Publishes `model.drift.detected` (§13.1) for each flagged
    run_type and returns the same signals.
    """
    policy = resolve_policy(db, tenant_id, None)
    min_runs = policy.constraints["monitoring_min_runs_per_window"]
    confidence_drop_threshold = policy.constraints["drift_confidence_drop_threshold"]
    mape_increase_ratio_threshold = policy.constraints["drift_mape_increase_ratio_threshold"]

    runs = db.scalars(
        select(OptimisationRun)
        .where(OptimisationRun.tenant_id == tenant_id)
        .where(OptimisationRun.status.in_(_TERMINAL_STATUSES))
        .order_by(OptimisationRun.created_at.asc())
    ).all()
    by_run_type: dict[str, list[OptimisationRun]] = defaultdict(list)
    for run in runs:
        by_run_type[run.run_type].append(run)

    signals: list[dict[str, Any]] = []
    for run_type, rows in by_run_type.items():
        if len(rows) < min_runs:
            continue
        midpoint = len(rows) // 2
        older, recent = rows[:midpoint], rows[midpoint:]

        older_confidences = [c for c in (_confidence_score(r) for r in older) if c is not None]
        recent_confidences = [c for c in (_confidence_score(r) for r in recent) if c is not None]
        if older_confidences and recent_confidences:
            older_avg = sum(older_confidences) / len(older_confidences)
            recent_avg = sum(recent_confidences) / len(recent_confidences)
            if older_avg - recent_avg >= confidence_drop_threshold:
                signal = {
                    "run_type": run_type, "metric": "confidence", "baseline": round(older_avg, 4), "recent": round(recent_avg, 4),
                }
                signals.append(signal)
                event_bus.publish(db, tenant_id, "model.drift.detected", signal, subject=run_type)

        older_mapes = [m for m in (_backtest_mape(r) for r in older) if m is not None]
        recent_mapes = [m for m in (_backtest_mape(r) for r in recent) if m is not None]
        if older_mapes and recent_mapes:
            older_avg = sum(older_mapes) / len(older_mapes)
            recent_avg = sum(recent_mapes) / len(recent_mapes)
            if older_avg > 0 and (recent_avg - older_avg) / older_avg >= mape_increase_ratio_threshold:
                signal = {
                    "run_type": run_type, "metric": "backtest_mape", "baseline": round(older_avg, 4), "recent": round(recent_avg, 4),
                }
                signals.append(signal)
                event_bus.publish(db, tenant_id, "model.drift.detected", signal, subject=run_type)

    return signals
