"""Controlled action endpoints — Integration Spec §12's two-step contract.

Recommendations become operational actions only through validate -> execute,
never directly: §12's own framing ("Any operational action remains a
proposal until an authorised user confirms it and policy permits
writeback") is enforced here, not just documented.

Directional note on app.maestro import: app/solvers/ never imports
app.maestro and vice versa (DP-03/INT-002, see app/maestro/base.py). This
module is neither — it's the control-plane orchestration layer (same tier
as app/api/v1/runs.py), and the dependency direction here is the opposite
of the read/ingestion side: connectors push canonical data INTO Tempo
(maestro -> core), but writeback is Tempo telling Maestro to push a
mutation OUT to a vendor (api -> maestro). That's the correct direction
for the target service boundary too — in production this becomes a real
API call to a separate Maestro service instead of the in-process function
call it is here.

`writeback_client` is a module-level name (matching `idempotency_store`/
`event_bus`'s existing style — no DI container in this codebase), so tests
substitute a `FakeWritebackClient` by monkeypatching it directly, the same
way connector tests substitute fake HTTP clients. It's the default for
every Overlay vendor target; `_get_writeback_client` swaps in a real,
non-stubbed `TempoNativeWritebackClient` (app/maestro/native_writeback.py)
for a `target.system == "tempo_native"` action instead — Standalone mode
doesn't need a vendor call to publish a roster or approve leave, since
Tempo owns those canonical tables directly.

execute_action always returns 202 with the business outcome in the body
(status: confirmed/rejected/partially_confirmed/unknown), the same design
already used for run completion (`completed` vs `completed_with_warnings`
is a 202 either way) — HTTP status codes carry request-level problems
(permission, expiry, drift), never the writeback's business outcome, which
can legitimately be "rejected" without the *request* having been invalid.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.action_tokens import ActionTokenInvalid, hash_token, issue_action_token, verify_action_token
from app.core.audit import write_audit
from app.core.events import event_bus
from app.core.idempotency import IdempotencyConflict, hash_payload, idempotency_store
from app.core.policy import resolve_policy
from app.dependencies import get_db, get_request_context, require_idempotency_key
from app.errors import (
    ActionNotFound,
    ActionTokenExpired,
    ActionTypeMismatch,
    ActionVersionDrift,
    AuthForbidden,
    ScopeError,
)
from app.maestro.native_writeback import TempoNativeWritebackClient
from app.maestro.writeback import WritebackClient, WritebackOutcome, default_writeback_client
from app.models.runs import ActionRequest, Recommendation, SourceVersionWatermark
from app.schemas.actions import (
    ACTION_TYPE_RUN_TYPE,
    RESOURCE_TYPE_BY_ACTION,
    ActionExecuteRequest,
    ActionResponse,
    ActionValidateRequest,
    ActionValidateResponse,
)
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["actions"])

writeback_client: WritebackClient = default_writeback_client


def _get_writeback_client(action: ActionRequest, db: Session) -> WritebackClient:
    """A `target.system == "tempo_native"` action gets a real, working
    client (app.maestro.native_writeback — Tempo committing directly to
    its own canonical tables, no vendor call needed) instead of the
    module-level `writeback_client` stand-in used for every Overlay
    vendor. Constructed fresh per call since it needs this request's `db`
    session; there is nothing to monkeypatch for tests here the way
    `writeback_client` is, because it's genuinely functional, not a stub.
    """
    if action.target.get("system") == "tempo_native":
        return TempoNativeWritebackClient(db, action.tenant_id)
    return writeback_client


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # SQLite round-trips DateTime(timezone=True) columns as naive even
    # though every value here is written in UTC (same fix demand_forecast.py
    # and others already apply).
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _canonical_payload(body: ActionValidateRequest) -> dict[str, Any]:
    return {
        "action_type": body.action_type,
        "recommendation_id": body.recommendation_id,
        "target": body.target.model_dump(),
        "expected_source_version": body.expected_source_version,
    }


def _watermark_key(tenant_id: str, action: ActionRequest) -> tuple[str, str, str, str]:
    resource_type = RESOURCE_TYPE_BY_ACTION[action.action_type]
    return (tenant_id, action.target["connection_id"], action.target["site_id"], resource_type)


def _current_version(db: Session, tenant_id: str, connection_id: str, site_id: str, resource_type: str) -> str | None:
    watermark = db.get(SourceVersionWatermark, (tenant_id, connection_id, site_id, resource_type))
    return watermark.version if watermark else None


def _bump_watermark(db: Session, tenant_id: str, action: ActionRequest) -> None:
    key = _watermark_key(tenant_id, action)
    watermark = db.get(SourceVersionWatermark, key)
    new_version = f"v{uuid.uuid4().hex[:12]}"
    if watermark is None:
        db.add(
            SourceVersionWatermark(
                tenant_id=tenant_id, connection_id=key[1], site_id=key[2], resource_type=key[3], version=new_version
            )
        )
    else:
        watermark.version = new_version
    db.flush()


def _apply_writeback_outcome(db: Session, context: RequestContext, action: ActionRequest, outcome: WritebackOutcome) -> None:
    action.status = outcome.status
    action.detail = outcome.detail
    db.flush()
    if outcome.status == "confirmed":
        _bump_watermark(db, context.tenant_id, action)
        event_bus.publish(db, context.tenant_id, "action.confirmed", {"action_id": action.action_id}, subject=action.action_id, correlation_id=context.correlation_id)
    elif outcome.status == "rejected":
        event_bus.publish(db, context.tenant_id, "action.failed", {"action_id": action.action_id, "reason": outcome.detail}, subject=action.action_id, correlation_id=context.correlation_id)
    # "unknown" / "partially_confirmed" get no terminal event yet — POST
    # /v1/actions/{id}/reconcile resolves them (§12.3, "reconciliation
    # required" and "Unknown writeback outcomes must be reconciled before
    # any replay; automatic blind retry is prohibited").


@router.post("/actions/validate", response_model=ActionValidateResponse)
def validate_action(
    request: ActionValidateRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ActionValidateResponse:
    if not context.has_permission("labour.plan"):
        raise AuthForbidden("caller lacks labour.plan permission required to validate an action")
    # No `context.site_ids and ...` guard -- see runs.py's _enforce_scope
    # for why (docs/tenant-isolation-inventory.md).
    if request.target.site_id not in context.site_ids:
        raise ScopeError("target site_id exceeds the caller's authorised scope")

    recommendation = db.get(Recommendation, request.recommendation_id)
    if recommendation is None or recommendation.tenant_id != context.tenant_id:
        raise ActionNotFound(f"recommendation '{request.recommendation_id}' not found or not visible in caller scope")
    if recommendation.expires_at is not None and _now() >= _aware(recommendation.expires_at):
        raise ActionTokenExpired(f"recommendation '{request.recommendation_id}' has expired")

    expected_run_type = ACTION_TYPE_RUN_TYPE[request.action_type]
    actual_run_type = recommendation.body.get("run_type")
    if actual_run_type != expected_run_type:
        raise ActionTypeMismatch(
            f"action_type '{request.action_type}' requires a '{expected_run_type}' recommendation, "
            f"but '{request.recommendation_id}' is a '{actual_run_type}' recommendation"
        )

    resource_type = RESOURCE_TYPE_BY_ACTION[request.action_type]
    current_version = _current_version(db, context.tenant_id, request.target.connection_id, request.target.site_id, resource_type)
    if current_version != request.expected_source_version:
        raise ActionVersionDrift(
            f"expected_source_version '{request.expected_source_version}' does not match the current tracked "
            f"version '{current_version}' for {resource_type} at site '{request.target.site_id}' — revalidate"
        )

    policy = resolve_policy(db, context.tenant_id, None)
    payload_hash = hash_payload(_canonical_payload(request))
    action_id = f"act_{uuid.uuid4().hex[:20]}"
    expires_at = _now() + timedelta(seconds=policy.constraints["action_token_ttl_seconds"])
    token = issue_action_token(action_id, payload_hash, expires_at)

    db.add(
        ActionRequest(
            action_id=action_id,
            tenant_id=context.tenant_id,
            recommendation_id=request.recommendation_id,
            snapshot_id=recommendation.snapshot_id,
            action_type=request.action_type,
            target=request.target.model_dump(),
            site_id=request.target.site_id,
            expected_source_version=request.expected_source_version,
            payload_hash=payload_hash,
            action_token_hash=hash_token(token),
            scope={"site_ids": [request.target.site_id]},
            status="validated",
            expires_at=expires_at,
        )
    )
    db.flush()

    explanation = recommendation.body.get("explanation", {})
    impact_summary = {
        "baseline": explanation.get("baseline"),
        "proposed": explanation.get("proposed"),
        "delta": explanation.get("delta"),
        "confidence": explanation.get("confidence"),
    }
    write_audit(
        db, context, request_name="POST /v1/actions/validate", outcome="validated",
        parameters={"action_type": request.action_type, "recommendation_id": request.recommendation_id},
        evidence_ref=explanation.get("evidence_ref"),
    )

    return ActionValidateResponse(
        action_id=action_id, action_token=token, status="validated", impact_summary=impact_summary, expires_at=expires_at
    )


def _get_owned_action(db: Session, context: RequestContext, action_id: str) -> ActionRequest:
    action = db.get(ActionRequest, action_id)
    if action is None or action.tenant_id != context.tenant_id:
        raise ActionNotFound(f"action '{action_id}' not found or not visible in caller scope")
    return action


@router.post("/actions", response_model=ActionResponse, status_code=202)
def execute_action(
    request: ActionExecuteRequest,
    context: RequestContext = Depends(get_request_context),
    idempotency_key: str = Depends(require_idempotency_key),
    db: Session = Depends(get_db),
) -> ActionResponse:
    endpoint = "POST /v1/actions"
    payload = request.model_dump(mode="json")
    try:
        existing = idempotency_store.get_or_reserve(context.tenant_id, endpoint, idempotency_key, payload)
    except IdempotencyConflict as exc:
        raise ScopeError(str(exc)) from exc
    if existing is not None:
        return ActionResponse(**existing.response)

    if not context.has_permission("labour.approve"):
        raise AuthForbidden("caller lacks labour.approve permission required to execute (approve) an action")

    action = _get_owned_action(db, context, request.action_id)
    if action.status != "validated":
        raise ActionTokenExpired(f"action '{request.action_id}' is not awaiting execution (status='{action.status}')")
    if _now() >= _aware(action.expires_at):
        raise ActionTokenExpired(f"action_token for '{request.action_id}' expired")

    payload_hash = hash_payload(_canonical_payload(request))
    if payload_hash != action.payload_hash or hash_token(request.action_token) != action.action_token_hash:
        raise ActionVersionDrift("action payload or token does not match the validated request — revalidate")
    try:
        verify_action_token(request.action_token, request.action_id, payload_hash)
    except ActionTokenInvalid as exc:
        raise ActionTokenExpired(str(exc)) from exc

    # Re-check drift at execute time, not just validate time — the source
    # may have moved between the two calls (§12.2).
    resource_type = RESOURCE_TYPE_BY_ACTION[action.action_type]
    current_version = _current_version(db, context.tenant_id, action.target["connection_id"], action.target["site_id"], resource_type)
    if current_version != action.expected_source_version:
        raise ActionVersionDrift(
            f"source version drifted to '{current_version}' since validation — revalidate"
        )

    action.approver_id = context.user_id
    action.status = "approved"
    db.flush()
    event_bus.publish(db, context.tenant_id, "action.approved", {"action_id": action.action_id}, subject=action.action_id, correlation_id=context.correlation_id)

    action.status = "submitted"
    db.flush()
    event_bus.publish(db, context.tenant_id, "action.submitted", {"action_id": action.action_id}, subject=action.action_id, correlation_id=context.correlation_id)

    outcome = _get_writeback_client(action, db).submit(action.action_type, action.target, _canonical_payload(request))
    _apply_writeback_outcome(db, context, action, outcome)

    write_audit(
        db, context, request_name=endpoint, outcome=action.status,
        parameters={"action_type": action.action_type, "recommendation_id": action.recommendation_id},
    )

    response = ActionResponse(action_id=action.action_id, status=action.status, detail=action.detail)
    idempotency_store.store(context.tenant_id, endpoint, idempotency_key, payload, response.model_dump(mode="json"))
    return response


@router.post("/actions/{action_id}/reconcile", response_model=ActionResponse, status_code=202)
def reconcile_action(
    action_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ActionResponse:
    """§12.3: 'Unknown writeback outcomes must be reconciled before any
    replay; automatic blind retry is prohibited.' Not one of the two named
    §8.2 endpoints (validate/execute) — a pragmatic necessary addition,
    since the spec's own acceptance criteria require reconciliation to
    exist somewhere. Safe to call on an already-terminal action: like
    cancel_run, it's best-effort and a no-op rather than an error.
    """
    if not context.has_permission("labour.approve"):
        raise AuthForbidden("caller lacks labour.approve permission required to reconcile an action")

    action = _get_owned_action(db, context, action_id)
    if action.status not in {"unknown", "partially_confirmed"}:
        return ActionResponse(action_id=action.action_id, status=action.status, detail=action.detail)

    outcome = _get_writeback_client(action, db).check_status(action.action_type, action.target, {"recommendation_id": action.recommendation_id})
    _apply_writeback_outcome(db, context, action, outcome)
    write_audit(db, context, request_name="POST /v1/actions/{action_id}/reconcile", outcome=action.status, parameters={"action_id": action_id})

    return ActionResponse(action_id=action.action_id, status=action.status, detail=action.detail)


@router.get("/actions")
def list_actions(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=500),
    cursor: str | None = Query(default=None),
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List view backing the console (services/tempo-console) — the same
    cursor-by-(created_at, id) pattern app/api/v1/runs.py's list_runs uses.
    """
    query = select(ActionRequest).where(ActionRequest.tenant_id == context.tenant_id)
    if status_filter:
        query = query.where(ActionRequest.status == status_filter)
    if cursor:
        cursor_action = db.get(ActionRequest, cursor)
        if cursor_action is not None:
            query = query.where(
                (ActionRequest.created_at < cursor_action.created_at)
                | ((ActionRequest.created_at == cursor_action.created_at) & (ActionRequest.action_id < cursor_action.action_id))
            )
    query = query.order_by(ActionRequest.created_at.desc(), ActionRequest.action_id.desc()).limit(limit)

    rows = db.scalars(query).all()
    return {
        "actions": [
            {
                "action_id": a.action_id, "action_type": a.action_type, "recommendation_id": a.recommendation_id,
                "status": a.status, "created_at": a.created_at,
            }
            for a in rows
        ],
        "next_cursor": rows[-1].action_id if len(rows) == limit else None,
    }


@router.get("/actions/{action_id}")
def get_action(
    action_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    action = _get_owned_action(db, context, action_id)
    return {
        "action_id": action.action_id,
        "action_type": action.action_type,
        "recommendation_id": action.recommendation_id,
        "target": action.target,
        "status": action.status,
        "detail": action.detail,
        "approver_id": action.approver_id,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }
