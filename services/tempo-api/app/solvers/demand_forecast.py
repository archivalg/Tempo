"""Demand Forecasting — AI Labour Optimisation Spec §3.1 / Appendix A.1.

Holt's linear (double exponential smoothing) trend model, implemented
without an external stats dependency. It's one of the three methods the
spec names ("Holt-Winters, SARIMA, or gradient-boosted trees") and is
enough to produce a genuine point forecast + confidence band + backtest
MAPE from real history — swap for GBM once there's enough tenant data and
feature history (calendar, promotions) to make that worth it (see
docs/roadmap.md).
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import DemandBucket
from app.schemas.runs import ConfidenceComponents, RunRequest
from app.solvers.base import InsufficientData, SolverOutcome

ALPHA = 0.4  # level smoothing
BETA = 0.2  # trend smoothing
Z_90 = 1.645

HISTORY_LOOKBACK_BUCKETS = 90


def _fit_holt_linear(series: list[float]) -> tuple[float, float, list[float]]:
    """Returns (level, trend, one_step_fitted_values)."""
    level = series[0]
    trend = series[1] - series[0]
    fitted = [level]
    for value in series[1:]:
        forecast = level + trend
        fitted.append(forecast)
        new_level = ALPHA * value + (1 - ALPHA) * (level + trend)
        new_trend = BETA * (new_level - level) + (1 - BETA) * trend
        level, trend = new_level, new_trend
    return level, trend, fitted


def _backtest_mape(actual: list[float], fitted: list[float]) -> float | None:
    errors = [abs(a - f) / a for a, f in zip(actual, fitted) if a > 0]
    if not errors:
        return None
    return sum(errors) / len(errors)


def forecast_demand(db: Session, tenant_id: str, site_ids: list[str], request: RunRequest) -> SolverOutcome:
    window = request.planning_window
    bucket = timedelta(minutes=window.bucket_minutes)
    horizon_buckets = max(1, math.ceil((window.end - window.start) / bucket))
    lookback_start = window.start - bucket * HISTORY_LOOKBACK_BUCKETS

    rows = db.scalars(
        select(DemandBucket)
        .where(DemandBucket.tenant_id == tenant_id)
        .where(DemandBucket.site_id.in_(site_ids))
        .where(DemandBucket.interval_start >= lookback_start)
        .where(DemandBucket.interval_start < window.start)
        .order_by(DemandBucket.activity, DemandBucket.interval_start)
    ).all()

    if not rows:
        raise InsufficientData(f"no historical demand_bucket rows for tenant '{tenant_id}' before the planning window")

    by_activity: dict[str, list[DemandBucket]] = defaultdict(list)
    for row in rows:
        by_activity[row.activity].append(row)

    forecasts: list[dict] = []
    naive_totals: dict[str, float] = {}
    model_totals: dict[str, float] = {}
    mapes: list[float] = []
    activities_with_trend = 0

    for activity, activity_rows in by_activity.items():
        series = [r.volume for r in activity_rows]
        last_observed = series[-1]
        naive_totals[activity] = last_observed * horizon_buckets

        if len(series) < 2:
            for h in range(1, horizon_buckets + 1):
                forecasts.append(
                    {
                        "activity": activity,
                        "bucket_start": (window.start + bucket * (h - 1)).isoformat(),
                        "point": last_observed,
                        "lower": last_observed,
                        "upper": last_observed,
                    }
                )
            model_totals[activity] = last_observed * horizon_buckets
            continue

        activities_with_trend += 1
        level, trend, fitted = _fit_holt_linear(series)
        mape = _backtest_mape(series, fitted)
        if mape is not None:
            mapes.append(mape)
        residuals = [a - f for a, f in zip(series, fitted)]
        sigma = math.sqrt(sum(r * r for r in residuals) / len(residuals)) if residuals else 0.0

        activity_total = 0.0
        for h in range(1, horizon_buckets + 1):
            point = max(0.0, level + trend * h)
            spread = Z_90 * sigma * math.sqrt(h)
            activity_total += point
            forecasts.append(
                {
                    "activity": activity,
                    "bucket_start": (window.start + bucket * (h - 1)).isoformat(),
                    "point": round(point, 2),
                    "lower": round(max(0.0, point - spread), 2),
                    "upper": round(point + spread, 2),
                }
            )
        model_totals[activity] = activity_total

    avg_mape = sum(mapes) / len(mapes) if mapes else None
    most_recent = max(r.interval_start for r in rows)
    if most_recent.tzinfo is None:
        # SQLite has no native datetime type — timestamps round-trip as naive
        # even through a DateTime(timezone=True) column. Every canonical
        # timestamp here is stored/produced in UTC, so this is safe.
        most_recent = most_recent.replace(tzinfo=timezone.utc)
    freshness_seconds = max(0.0, (window.start - most_recent).total_seconds())
    freshness_days = freshness_seconds / 86400

    missing_evidence = []
    if activities_with_trend < len(by_activity):
        missing_evidence.append(
            f"{len(by_activity) - activities_with_trend} of {len(by_activity)} activities have <2 historical "
            "buckets and fall back to a naive (last-observed) forecast"
        )
    if avg_mape is None:
        missing_evidence.append("insufficient history to backtest forecast error")

    return SolverOutcome(
        result={
            "forecast": forecasts,
            "backtest_mape": round(avg_mape, 4) if avg_mape is not None else None,
            "kpis": {"activities_forecast": len(by_activity), "horizon_buckets": horizon_buckets},
        },
        baseline={"method": "naive_last_observed", "total_by_activity": naive_totals},
        proposed={"method": "holt_linear", "total_by_activity": model_totals},
        delta={
            activity: round(model_totals[activity] - naive_totals[activity], 2)
            for activity in model_totals
        },
        confidence_components=ConfidenceComponents(
            completeness=round(activities_with_trend / len(by_activity), 4) if by_activity else 0.0,
            freshness=round(max(0.0, 1 - freshness_days / 7), 4),
            mapping_quality=1.0,
            forecast_validation=round(max(0.0, 1 - min(avg_mape, 1.0)), 4) if avg_mape is not None else 0.5,
            constraint_coverage=1.0,
            solution_quality=1.0 if activities_with_trend == len(by_activity) else 0.7,
        ),
        primary_drivers=[f"Fitted Holt linear trend over {len(rows)} historical buckets across {len(by_activity)} activities"],
        missing_evidence=missing_evidence,
        assumptions=[f"forecast method fixed to Holt linear smoothing (alpha={ALPHA}, beta={BETA})"],
        feasibility="feasible",
    )
