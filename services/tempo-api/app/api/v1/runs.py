"""Run creation and lifecycle endpoints — §8.2 capability catalogue.

Phase 0 exit outcome (Integration Spec §18): "Prime can call a stubbed Tempo
run end-to-end with governed evidence." The four run types below execute
through the real snapshot/lifecycle/confidence/audit/event pipeline; the
`result` numbers themselves are deterministic stand-ins until Phase A wires
in the actual forecasting/MILP/CP-SAT solvers (see docs/roadmap.md). Every
other run_type in Appendix C is a legal request that returns
TEMPO-RUN-004 (not yet implemented for this phase) rather than a 404,
so Prime's tool schema doesn't need to change as phases land.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core import lifecycle
from app.core.audit import write_audit
from app.core.confidence import compute_confidence
from app.core.events import event_bus
from app.core.idempotency import IdempotencyConflict, idempotency_store
from app.dependencies import get_db, get_request_context, require_idempotency_key
from app.errors import AuthForbidden, RunNotFound, RunTerminal, RunTypeNotImplemented, ScopeError
from app.models.runs import OptimisationRun
from app.schemas.readiness import CAPABILITY_REQUIRED_DOMAINS
from app.schemas.runs import (
    IMPLEMENTED_RUN_TYPES,
    ConfidenceComponents,
    RunRequest,
    RunResponse,
)
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["runs"])

_RUN_TYPE_TO_CAPABILITY = {
    "demand_forecast": "forecast.demand",
    "labour_requirement": "forecast.labour_requirement",
    "workforce_mix": "optimize.mix",
    "named_roster": "optimize.roster",
}

_RUN_TYPE_TO_MODEL = {
    "demand_forecast": ("demand_forecast_gbm", "1.0.0-stub", "gbm"),
    "labour_requirement": ("labour_requirement_translation", "1.0.0-stub", "deterministic"),
    "workforce_mix": ("workforce_mix", "1.0.0-stub", "milp"),
    "named_roster": ("named_roster", "1.0.0-stub", "cp-sat"),
}


def _enforce_scope(context: RequestContext, request: RunRequest) -> None:
    if context.site_ids and any(site not in context.site_ids for site in request.scope.site_ids):
        raise ScopeError("requested site_ids exceed the caller's authorised scope")
    if context.customer_ids and any(c not in context.customer_ids for c in request.scope.customer_ids):
        raise ScopeError("requested customer_ids exceed the caller's authorised scope")


def _stub_result(run_type: str, request: RunRequest) -> dict[str, Any]:
    # Deterministic placeholder numbers — Phase A replaces this function's
    # body with a real solver call; the contract around it does not change.
    if run_type == "workforce_mix" or run_type == "named_roster":
        return {
            "assignments": [],
            "kpis": {
                "labour_cost": {"amount": "0.00", "currency": "AUD"},
                "coverage_pct": 0.0,
            },
        }
    return {"forecast": [], "kpis": {}}


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

    capability = _RUN_TYPE_TO_CAPABILITY[run_type]
    required_domains = CAPABILITY_REQUIRED_DOMAINS.get(capability, [])
    # Phase 0 stub: readiness gating exists structurally (see readiness.py)
    # but run creation does not yet block on it — Phase A wires the same
    # check used by GET /v1/data-readiness in here before queuing.
    warnings: list[str] = []

    lifecycle.require_transition(run.status, "queued")
    run.status = "queued"
    event_bus.publish(db, context.tenant_id, "run.started", {"run_id": run_id}, subject=run_id, correlation_id=context.correlation_id)

    lifecycle.require_transition(run.status, "running")
    run.status = "running"

    model_name, model_version, solver = _RUN_TYPE_TO_MODEL[run_type]
    result = _stub_result(run_type, request)
    confidence = compute_confidence(
        ConfidenceComponents(
            completeness=0.7 if required_domains else 1.0,
            freshness=1.0,
            mapping_quality=0.9,
            forecast_validation=0.8,
            constraint_coverage=0.8,
            solution_quality=1.0,
        ),
        reasons=warnings or ["Phase 0 stub result — no live canonical data consumed yet"],
    )
    explanation = {
        "baseline": {},
        "proposed": {},
        "delta": {},
        "dollar_value": None,
        "confidence": confidence.model_dump(),
        "primary_drivers": ["Phase 0 stub — deterministic placeholder, not a solver decision"],
        "alternatives": [],
        "data_lineage": {"snapshot_id": snapshot_id, "source_systems": ["tempo_native"]},
        "freshness": {"source_max_age_seconds": 0},
        "missing_evidence": warnings,
        "assumptions": ["Phase A replaces this stub with the real solver"],
        "feasibility": "feasible",
        "evidence_ref": f"evi_{uuid.uuid4().hex[:20]}",
    }
    lineage = {
        "snapshot_id": snapshot_id,
        "source_systems": ["tempo_native"],
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
