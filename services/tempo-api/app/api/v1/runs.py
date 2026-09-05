"""Run creation and lifecycle endpoints — §8.2 capability catalogue.

Phase A wires the four run types to real solvers (app/solvers/*): Holt
linear demand forecasting, deterministic labour-requirement translation, an
OR-Tools MILP workforce mix, and an OR-Tools CP-SAT named roster — see each
module's docstring for the scope reductions taken to keep them tractable
without a real Maestro feed yet. Every other run_type in Appendix C is
still a legal request that returns TEMPO-RUN-004 rather than a 404, so
Prime's tool schema doesn't need to change as later phases land.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core import lifecycle
from app.core.audit import write_audit
from app.core.confidence import compute_confidence
from app.core.events import event_bus
from app.core.idempotency import IdempotencyConflict, idempotency_store
from app.dependencies import get_db, get_request_context, require_idempotency_key
from app.errors import AuthForbidden, DataNotReady, RunNotFound, RunTerminal, RunTypeNotImplemented, ScopeError
from app.models.runs import OptimisationRun
from app.schemas.runs import IMPLEMENTED_RUN_TYPES, RunRequest, RunResponse
from app.schemas.tenancy import RequestContext
from app.solvers.base import InsufficientData, SolverOutcome
from app.solvers.demand_forecast import forecast_demand
from app.solvers.labour_requirement import translate_labour_requirement
from app.solvers.named_roster import solve_named_roster
from app.solvers.workforce_mix import solve_workforce_mix

router = APIRouter(tags=["runs"])

_RUN_TYPE_TO_MODEL = {
    "demand_forecast": ("demand_forecast_holt_linear", "1.0.0", "holt-linear"),
    "labour_requirement": ("labour_requirement_translation", "1.0.0", "deterministic"),
    "workforce_mix": ("workforce_mix", "1.0.0", "milp-cbc"),
    "named_roster": ("named_roster", "1.0.0", "cp-sat"),
}

_SOLVERS: dict[str, Callable[[Session, str, list[str], RunRequest], SolverOutcome]] = {
    "demand_forecast": forecast_demand,
    "labour_requirement": translate_labour_requirement,
    "workforce_mix": solve_workforce_mix,
    "named_roster": solve_named_roster,
}


def _enforce_scope(context: RequestContext, request: RunRequest) -> None:
    if context.site_ids and any(site not in context.site_ids for site in request.scope.site_ids):
        raise ScopeError("requested site_ids exceed the caller's authorised scope")
    if context.customer_ids and any(c not in context.customer_ids for c in request.scope.customer_ids):
        raise ScopeError("requested customer_ids exceed the caller's authorised scope")
    if not request.scope.site_ids:
        raise ScopeError("request scope must specify at least one site_id — solvers run per-site")


@router.post("/optimisations/{run_type}", response_model=RunResponse, status_code=202)
def create_run(
    run_type: str,
    request: RunRequest,
    context: RequestContext = Depends(get_request_context),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
) -> RunResponse:
    endpoint = f"POST /v1/optimisations/{run_type}"
    payload = request.model_dump(mode="json")

    try:
        existing = idempotency_store.get_or_reserve(context.tenant_id, endpoint, idempotency_key, payload)
    except IdempotencyConflict as exc:
        raise ScopeError(str(exc)) from exc
    if existing is not None:
        return RunResponse(**existing.response)

    if run_type not in IMPLEMENTED_RUN_TYPES:
        raise RunTypeNotImplemented(f"run_type '{run_type}' is not implemented in the current roadmap phase")
    if not context.has_permission("labour.plan"):
        raise AuthForbidden("caller lacks labour.plan permission required to create optimisation runs")

    _enforce_scope(context, request)

    run_id = f"run_{uuid.uuid4().hex[:20]}"
    snapshot_id = f"snap_{uuid.uuid4().hex[:20]}"
    run = OptimisationRun(
        run_id=run_id,
        tenant_id=context.tenant_id,
        run_type=run_type,
        status="accepted",
        request=payload,
        snapshot_id=snapshot_id,
        policy_version=request.configuration.policy_version,
        model_version=request.configuration.model_version,
        idempotency_key=idempotency_key,
        correlation_id=context.correlation_id,
    )
    db.add(run)
    db.flush()
    event_bus.publish(db, context.tenant_id, "run.accepted", {"run_id": run_id, "run_type": run_type}, subject=run_id, correlation_id=context.correlation_id)

    lifecycle.require_transition(run.status, "validating")
    run.status = "validating"

    lifecycle.require_transition(run.status, "queued")
    run.status = "queued"
    event_bus.publish(db, context.tenant_id, "run.started", {"run_id": run_id}, subject=run_id, correlation_id=context.correlation_id)

    lifecycle.require_transition(run.status, "running")
    run.status = "running"

    try:
        outcome = _SOLVERS[run_type](db, context.tenant_id, request.scope.site_ids, request)
    except InsufficientData as exc:
        # No persisted "failed" run for a validation-time rejection — the
        # request never produced a snapshot worth auditing as a run; the
        # whole transaction (including the run row above) rolls back.
        raise DataNotReady(str(exc)) from exc

    warnings = list(outcome.missing_evidence)
    confidence = compute_confidence(outcome.confidence_components, reasons=warnings or ["no data-quality issues detected"])
    explanation = {
        "baseline": outcome.baseline,
        "proposed": outcome.proposed,
        "delta": outcome.delta,
        "dollar_value": outcome.dollar_value,
        "confidence": confidence.model_dump(),
        "primary_drivers": outcome.primary_drivers,
        "alternatives": outcome.alternatives,
        "data_lineage": {"snapshot_id": snapshot_id, "source_systems": outcome.source_systems},
        "freshness": {"source_max_age_seconds": 0},
        "missing_evidence": outcome.missing_evidence,
        "assumptions": outcome.assumptions,
        "feasibility": outcome.feasibility,
        "evidence_ref": f"evi_{uuid.uuid4().hex[:20]}",
    }
    result = outcome.result
    lineage = {
        "snapshot_id": snapshot_id,
        "source_systems": outcome.source_systems,
        "policy_version": request.configuration.policy_version,
    }

    final_status = "completed_with_warnings" if warnings else "completed"
    lifecycle.require_transition(run.status, final_status)
    run.status = final_status
    run.result = result
    run.explanation = explanation
    run.lineage = lineage
    run.completed_at = datetime.now(timezone.utc)
    db.flush()

    event_bus.publish(
        db,
        context.tenant_id,
        "run.completed",
        {"run_id": run_id, "status": final_status},
        subject=run_id,
        correlation_id=context.correlation_id,
    )
    write_audit(
        db,
        context,
        request_name=endpoint,
        outcome=final_status,
        parameters={"run_type": run_type, "scope": payload["scope"]},
        run_id=run_id,
        evidence_ref=explanation["evidence_ref"],
    )

    response = RunResponse(
        run_id=run_id,
        run_type=run_type,
        status=run.status,
        created_at=run.created_at,
        links={"self": f"/v1/runs/{run_id}", "cancel": f"/v1/runs/{run_id}/cancel"},
        input_snapshot_id=snapshot_id,
        effective_scope=request.scope,
        warnings=warnings,
    )
    idempotency_store.store(context.tenant_id, endpoint, idempotency_key, payload, response.model_dump(mode="json"))
    return response


def _get_owned_run(db: Session, context: RequestContext, run_id: str) -> OptimisationRun:
    run = db.get(OptimisationRun, run_id)
    if run is None or run.tenant_id != context.tenant_id:
        raise RunNotFound(f"run '{run_id}' not found or not visible in caller scope")
    return run


@router.get("/runs/{run_id}")
def get_run(
    run_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run = _get_owned_run(db, context, run_id)
    if lifecycle.is_terminal(run.status) and run.status in {"completed", "completed_with_warnings"}:
        return {
            "run_id": run.run_id,
            "status": run.status,
            "model": dict(zip(("name", "version", "solver"), _RUN_TYPE_TO_MODEL.get(run.run_type, ("unknown", "0", "unknown")))),
            "result": run.result,
            "explanation": run.explanation,
            "lineage": run.lineage,
            "completed_at": run.completed_at,
            "supersedes_run_id": run.supersedes_run_id,
        }
    return {
        "run_id": run.run_id,
        "run_type": run.run_type,
        "status": run.status,
        "created_at": run.created_at,
        "input_snapshot_id": run.snapshot_id,
    }


@router.post("/runs/{run_id}/cancel")
def cancel_run(
    run_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run = _get_owned_run(db, context, run_id)
    if lifecycle.is_terminal(run.status):
        # §10: "Best effort; terminal runs unchanged."
        return {"run_id": run.run_id, "status": run.status}
    target = "cancelled" if run.status == "queued" else "cancel_requested"
    lifecycle.require_transition(run.status, target)
    run.status = target
    db.flush()
    return {"run_id": run.run_id, "status": run.status}


@router.post("/run-comparisons")
def compare_runs(
    body: dict[str, list[str]],
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    run_ids = body.get("run_ids", [])
    if len(run_ids) < 2:
        raise ScopeError("run-comparisons requires at least two run_ids")
    runs = [_get_owned_run(db, context, run_id) for run_id in run_ids]
    for run in runs:
        if run.status not in {"completed", "completed_with_warnings"}:
            raise RunTerminal(f"run '{run.run_id}' is not in a comparable terminal state")
    return {
        "run_ids": run_ids,
        "kpis": [{"run_id": run.run_id, "kpis": (run.result or {}).get("kpis", {})} for run in runs],
    }
