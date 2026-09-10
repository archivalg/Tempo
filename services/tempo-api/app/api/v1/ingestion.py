"""Canonical ingestion API — INT-02: "Expose a versioned canonical
ingestion contract using authenticated APIs or durable events." Appendix
A: "POST /v1/ingestion/events | Accept canonical events from Tempo
connectors or an optional Maestro adapter. | Authenticate the service
principal, validate tenant binding and contract version."

Before this endpoint, `app.core.ingestion.apply_canonical_envelope` (§6.2's
"applies a canonical envelope to Tempo's canonical store") was only ever
called from inside a connector's own in-process Python code
(app/maestro/deputy/connector.py and friends) — despite
`app.schemas.envelope.CanonicalEnvelope`'s own docstring claiming
"Phase 0 accepts these directly at /v1/canonical/ingest," no such endpoint
has ever existed in this codebase. This is that endpoint, named to match
Appendix A rather than the stale docstring reference (which is now
corrected to point here).

Gated on `labour.writeback` (§5.2: "Restricted integration role... Submit
approved changes to a source system") — the closest existing permission to
"is a trusted integration/service principal," reused rather than inventing
a new one, since Phase 1's `ServiceClient`/service-credential issuance
(SEC-22) isn't wired to real authentication yet (ADR-0001).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.ingestion import IngestionResult, apply_canonical_envelope, supported_entity_types
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, ScopeError
from app.schemas.envelope import CanonicalEnvelope
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["ingestion"])

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}


class IngestionEventRequest(BaseModel):
    envelope: CanonicalEnvelope
    entity_type: str
    fields: dict[str, Any]


class IngestionEventResponse(BaseModel):
    status: str
    entity_id: str | None = None


@router.post("/ingestion/events", response_model=IngestionEventResponse, status_code=202)
def ingest_canonical_event(
    request: IngestionEventRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> IngestionEventResponse:
    if not context.has_permission("labour.writeback"):
        raise AuthForbidden("caller lacks labour.writeback permission required to submit canonical ingestion events")

    # Tenant binding (Appendix A) -- the caller's own authenticated tenant
    # must match what the envelope claims, never trusted from the envelope
    # alone (the same "a requested identifier is a selector, never
    # authority" posture §6.4 takes elsewhere).
    if request.envelope.tenant_id != context.tenant_id:
        raise ScopeError("envelope tenant_id does not match caller's authenticated tenant")
    if context.site_ids and request.envelope.site_id not in context.site_ids:
        raise ScopeError("envelope site_id exceeds the caller's authorised scope")

    # Contract version (Appendix A) -- reject anything this codebase
    # doesn't know how to interpret rather than guess at a newer/older
    # shape. §18.2: "Breaking changes require a new contract version."
    if request.envelope.schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ScopeError(
            f"envelope schema_version '{request.envelope.schema_version}' is not supported "
            f"(supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)})"
        )
    if request.entity_type not in supported_entity_types():
        raise ScopeError(
            f"entity_type '{request.entity_type}' has no registered canonical upsert "
            f"(supported: {sorted(supported_entity_types())})"
        )

    result: IngestionResult = apply_canonical_envelope(db, request.envelope, request.entity_type, request.fields)
    return IngestionEventResponse(status=result.status, entity_id=result.entity_id)
