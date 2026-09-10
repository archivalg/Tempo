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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.connector_catalogue import CONNECTOR_CATALOGUE, get_connector
from app.dependencies import get_db, get_request_context
from app.errors import AuthForbidden, RunNotFound, ScopeError
from app.maestro.credentials import credential_store
from app.models.canonical import TenantScope
from app.models.connectors import ConnectorCheckpoint, ConnectorCredentialReference, IngestionDeadLetter, MaestroConnection
from app.schemas.onboarding import (
    ConnectionCreateRequest,
    ConnectionCredentialsRequest,
    ConnectionHealthResponse,
    ConnectionListResponse,
    ConnectionResponse,
    ConnectionTestResponse,
    ConnectorCheckpointSummary,
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


def _get_owned_connection(db: Session, context: RequestContext, connection_id: str) -> MaestroConnection:
    connection = db.get(MaestroConnection, connection_id)
    if connection is None or connection.tenant_id != context.tenant_id:
        raise RunNotFound(f"connection '{connection_id}' not found or not visible in caller scope")
    return connection


@router.post("/connections/{connection_id}/credentials", response_model=ConnectionResponse, status_code=201)
def store_connection_credentials(
    connection_id: str,
    request: ConnectionCredentialsRequest,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ConnectionResponse:
    """INT-03/Appendix A. Never returns the secret back — only the
    connection's updated status. See app/maestro/credentials.py's module
    docstring for exactly what "storing" a credential means here (an
    in-process, non-durable stand-in — a real deployment routes this to
    OCI Vault and passes Tempo only a reference).
    """
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to store connection credentials")
    connection = _get_owned_connection(db, context, connection_id)
    if connection.status in ("revoked",):
        raise ScopeError(f"connection '{connection_id}' is revoked and cannot accept new credentials")

    reference = credential_store.store(connection_id, request.secret)
    existing = db.get(ConnectorCredentialReference, connection_id)
    if existing is None:
        db.add(
            ConnectorCredentialReference(
                connection_id=connection_id, tenant_id=context.tenant_id, vault_secret_reference=reference
            )
        )
    else:
        existing.vault_secret_reference = reference
        existing.rotated_at = datetime.now(timezone.utc)
    connection.status = "credentials_stored"
    db.flush()
    return ConnectionResponse(
        connection_id=connection.connection_id, tenant_id=connection.tenant_id, source_system=connection.source_system,
        site_id=connection.site_id, display_name=connection.display_name, status=connection.status,
        created_at=_aware(connection.created_at),
    )


@router.post("/connections/{connection_id}/test", response_model=ConnectionTestResponse)
def test_connection(
    connection_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ConnectionTestResponse:
    """Appendix A: "Validate credentials and vendor access. Never return
    credential material." No real vendor client exists for any catalogued
    source_system (see app/maestro's own read clients' "unverified against
    a live tenant" disclosure), so this can only honestly validate that a
    credential reference was stored — never that a vendor accepted it.
    """
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to test a connection")
    connection = _get_owned_connection(db, context, connection_id)
    credential = db.get(ConnectorCredentialReference, connection_id)
    if credential is None:
        return ConnectionTestResponse(
            connection_id=connection_id, ok=False, detail="no credentials stored for this connection yet"
        )
    result = credential_store.test(credential.vault_secret_reference)
    return ConnectionTestResponse(connection_id=connection_id, ok=result.ok, detail=result.detail)


@router.post("/connections/{connection_id}/activate", response_model=ConnectionResponse)
def activate_connection(
    connection_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ConnectionResponse:
    """Appendix A: "Start scheduled synchronisation." No scheduler exists
    yet (Phase 4/JOB-08) — activating today only marks intent; nothing
    actually begins polling a vendor. Requires a stored credential
    reference, since activating a connection with nothing to authenticate
    with would be a lie the status field tells forever after.
    """
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to activate a connection")
    connection = _get_owned_connection(db, context, connection_id)
    if db.get(ConnectorCredentialReference, connection_id) is None:
        raise ScopeError(f"connection '{connection_id}' has no stored credentials — call .../credentials first")
    connection.status = "active"
    db.flush()
    return ConnectionResponse(
        connection_id=connection.connection_id, tenant_id=connection.tenant_id, source_system=connection.source_system,
        site_id=connection.site_id, display_name=connection.display_name, status=connection.status,
        created_at=_aware(connection.created_at),
    )


@router.post("/connections/{connection_id}/suspend", response_model=ConnectionResponse)
def suspend_connection(
    connection_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ConnectionResponse:
    """A reversible pause — the credential reference is kept, unlike
    revoke. Safe to call on any non-revoked connection, even one that was
    never activated (best-effort, same convention as app/api/v1/actions.py's
    reconcile endpoint being a no-op on an already-terminal action).
    """
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to suspend a connection")
    connection = _get_owned_connection(db, context, connection_id)
    if connection.status == "revoked":
        raise ScopeError(f"connection '{connection_id}' is revoked and cannot be suspended")
    connection.status = "suspended"
    db.flush()
    return ConnectionResponse(
        connection_id=connection.connection_id, tenant_id=connection.tenant_id, source_system=connection.source_system,
        site_id=connection.site_id, display_name=connection.display_name, status=connection.status,
        created_at=_aware(connection.created_at),
    )


@router.post("/connections/{connection_id}/revoke", response_model=ConnectionResponse)
def revoke_connection(
    connection_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ConnectionResponse:
    """Terminal — revokes the stored credential (app.maestro.credentials.CredentialStore.revoke)
    and leaves the connection unable to re-activate without storing a
    fresh credential. Idempotent: revoking an already-revoked connection
    is a no-op, not an error.
    """
    if not context.has_permission("labour.configure"):
        raise AuthForbidden("caller lacks labour.configure permission required to revoke a connection")
    connection = _get_owned_connection(db, context, connection_id)
    credential = db.get(ConnectorCredentialReference, connection_id)
    if credential is not None:
        credential_store.revoke(credential.vault_secret_reference)
        db.delete(credential)
    connection.status = "revoked"
    db.flush()
    return ConnectionResponse(
        connection_id=connection.connection_id, tenant_id=connection.tenant_id, source_system=connection.source_system,
        site_id=connection.site_id, display_name=connection.display_name, status=connection.status,
        created_at=_aware(connection.created_at),
    )


@router.get("/connections/{connection_id}/health", response_model=ConnectionHealthResponse)
def get_connection_health(
    connection_id: str,
    context: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
) -> ConnectionHealthResponse:
    """INT-11 — see ConnectionHealthResponse's own docstring for exactly
    what "lag" and the absence of a record-count field mean here: no
    connection in this codebase has ever actually run an ingestion sync
    (INT-05/INT-06 are blocked without a real vendor sandbox), so a
    freshly registered connection's health is honestly empty, not faked.
    """
    if not context.has_permission("labour.read"):
        raise AuthForbidden("caller lacks labour.read permission required to view connection health")
    connection = _get_owned_connection(db, context, connection_id)

    checkpoints = db.scalars(
        select(ConnectorCheckpoint).where(ConnectorCheckpoint.tenant_id == context.tenant_id).where(
            ConnectorCheckpoint.connection_id == connection_id
        )
    ).all()
    checkpoint_summaries = [
        ConnectorCheckpointSummary(entity_type=c.entity_type, watermark=c.watermark, updated_at=_aware(c.updated_at))
        for c in checkpoints
    ]
    last_sync = max((c.updated_at for c in checkpoints), default=None)
    lag_seconds = (datetime.now(timezone.utc) - _aware(last_sync)).total_seconds() if last_sync else None

    unresolved = db.scalar(
        select(func.count())
        .select_from(IngestionDeadLetter)
        .where(IngestionDeadLetter.tenant_id == context.tenant_id)
        .where(IngestionDeadLetter.connection_id == connection_id)
        .where(IngestionDeadLetter.resolved.is_(False))
    )
    total = db.scalar(
        select(func.count())
        .select_from(IngestionDeadLetter)
        .where(IngestionDeadLetter.tenant_id == context.tenant_id)
        .where(IngestionDeadLetter.connection_id == connection_id)
    )

    return ConnectionHealthResponse(
        connection_id=connection_id,
        status=connection.status,
        checkpoints=checkpoint_summaries,
        last_successful_sync=_aware(last_sync) if last_sync else None,
        lag_seconds=lag_seconds,
        dead_letters_unresolved=unresolved or 0,
        dead_letters_total=total or 0,
    )
