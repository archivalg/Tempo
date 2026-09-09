"""Self-service onboarding — Phase F (§18): "connector catalogue" and
"self-service onboarding".

Before this, a tenant's `TenantScope` and connector rows only ever existed
because an engineer ran a seed script or a direct DB insert
(services/tempo-api README's Phase 0 "Canonical ingestion" simplification).
These endpoints let a Tenant Admin (`labour.configure`, §5.2) declare both
through the API instead. What this does *not* do — and cannot, without a
credential vault this scaffold doesn't have — is configure a live vendor
credential or trigger ingestion; a registered `MaestroConnection` stays
`pending_credentials` until a real deployment wires up an actual client
(see app/models/connectors.py's `MaestroConnection` docstring, and Phase
E's writeback connector for the same class of disclosed gap).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.connector_catalogue import CONNECTOR_CATALOGUE, get_connector
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, ScopeError
from app.models.canonical import TenantScope
from app.models.connectors import MaestroConnection
from app.schemas.onboarding import (
    ConnectionCreateRequest,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectorDescriptorResponse,
    TenantScopeCreateRequest,
    TenantScopeResponse,
)
from app.schemas.tenancy import RequestContext

router = APIRouter(tags=["onboarding"])


def _aware(value: datetime) -> datetime:
    # SQLite round-trips DateTime(timezone=True) columns as naive even
    # though every value here is written in UTC — a freshly-created ORM
    # instance still carries its original tz-aware Python datetime, so
    # this only bites on a value re-read from the DB in a later request
    # (same fix app/api/v1/actions.py and app/solvers/demand_forecast.py
    # already apply).
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class _ConnectionCreateRequestValidated(ConnectionCreateRequest):
    # Narrows source_system to what app/maestro/ actually implements —
    # Appendix C's source_system enum also has tempo_native/lms/tms/erp/
    # finance/manual_approved, which are data-lineage labels, not
    # connectors this catalogue registers.
    source_system: Literal["deputy", "ukg_pro_wfm", "ukg_ready", "wms"]


@router.get("/connectors", response_model=list[ConnectorDescriptorResponse])
def list_connectors(context: RequestContext = Depends(get_request_context)) -> list[ConnectorDescriptorResponse]:
    if not context.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read permission required to view the connector catalogue")
    return [
        ConnectorDescriptorResponse(
            source_system=c.source_system, display_name=c.display_name, entity_types=list(c.entity_types),
            auth_type=c.auth_type, status=c.status, notes=c.notes,
        )
        for c in CONNECTOR_CATALOGUE
    ]


@router.post("/tenant-scopes", response_model=TenantScopeResponse, status_code=201)
def create_tenant_scope(
    request: TenantScopeCreateRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> TenantScopeResponse:
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to register a tenant scope")

    existing = db.get(TenantScope, (context.tenant_id, request.site_id))
    if existing is None:
        existing = TenantScope(
            tenant_id=context.tenant_id, site_id=request.site_id,
            company_id=request.company_id, customer_id=request.customer_id,
        )
        db.add(existing)
        db.flush()
    return TenantScopeResponse(
        tenant_id=existing.tenant_id, site_id=existing.site_id,
        company_id=existing.company_id, customer_id=existing.customer_id, created_at=_aware(existing.created_at),
    )


@router.get("/tenant-scopes", response_model=list[TenantScopeResponse])
def list_tenant_scopes(
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> list[TenantScopeResponse]:
    if not context.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read permission required to view tenant scopes")
    rows = db.scalars(select(TenantScope).where(TenantScope.tenant_id == context.tenant_id)).all()
    return [
        TenantScopeResponse(tenant_id=r.tenant_id, site_id=r.site_id, company_id=r.company_id, customer_id=r.customer_id, created_at=_aware(r.created_at))
        for r in rows
    ]


@router.post("/connections", response_model=ConnectionResponse, status_code=201)
def create_connection(
    request: _ConnectionCreateRequestValidated,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ConnectionResponse:
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to register a connection")

    if get_connector(request.source_system) is None:
        raise ScopeError(f"'{request.source_system}' is not in the connector catalogue")
    if db.get(TenantScope, (context.tenant_id, request.site_id)) is None:
        raise ScopeError(
            f"site '{request.site_id}' has no registered tenant scope — "
            "register one via POST /v1/tenant-scopes before adding a connection for it"
        )

    connection = MaestroConnection(
        tenant_id=context.tenant_id, source_system=request.source_system,
        site_id=request.site_id, display_name=request.display_name,
    )
    db.add(connection)
    db.flush()
    return ConnectionResponse(
        connection_id=connection.connection_id, tenant_id=connection.tenant_id,
        source_system=connection.source_system, site_id=connection.site_id,
        display_name=connection.display_name, status=connection.status, created_at=_aware(connection.created_at),
    )


@router.get("/connections", response_model=ConnectionListResponse)
def list_connections(
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ConnectionListResponse:
    if not context.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read permission required to view connections")
    rows = db.scalars(select(MaestroConnection).where(MaestroConnection.tenant_id == context.tenant_id)).all()
    return ConnectionListResponse(
        connections=[
            ConnectionResponse(
                connection_id=r.connection_id, tenant_id=r.tenant_id, source_system=r.source_system,
                site_id=r.site_id, display_name=r.display_name, status=r.status, created_at=_aware(r.created_at),
            )
            for r in rows
        ]
    )
