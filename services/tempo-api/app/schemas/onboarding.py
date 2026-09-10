"""Self-service onboarding contracts — Phase F (§18), extended by Phase 3
(INT-03/INT-04) with the credential lifecycle Appendix A names:
POST /v1/connections/{id}/test, /activate, plus /credentials, /suspend
and /revoke this pass adds to make those two real.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# "disabled" existed here before this pass but nothing ever set it -- a
# declared-but-dead status value. Replaced with the real lifecycle
# app/maestro/credentials.py and app/api/v1/onboarding.py's new endpoints
# actually drive: pending_credentials -> credentials_stored -> active, with
# suspended/revoked reachable from active. None of these transitions imply
# a real vendor call ever validated anything -- see
# app/maestro/credentials.py's own module docstring for exactly what "test"
# does and doesn't verify without a real vendor endpoint to call.
ConnectionStatus = Literal["pending_credentials", "credentials_stored", "active", "suspended", "revoked"]


class ConnectionCredentialsRequest(BaseModel):
    """Dev-only shape: a real deployment's Tenant Admin console should
    call OCI Vault directly and pass Tempo only a reference (INT-03) --
    accepting a raw secret dict here at all is the disclosed local-dev
    stand-in `app.maestro.credentials.InMemoryCredentialStore` exists for,
    not a pattern to keep once a real Vault integration exists.
    """

    secret: dict[str, Any]


class ConnectionTestResponse(BaseModel):
    connection_id: str
    ok: bool
    detail: str


class ConnectorDescriptorResponse(BaseModel):
    source_system: str
    display_name: str
    entity_types: list[str]
    auth_type: str
    status: str
    notes: str


class TenantScopeCreateRequest(BaseModel):
    site_id: str
    company_id: str | None = None
    customer_id: str | None = None


class TenantScopeResponse(BaseModel):
    tenant_id: str
    site_id: str
    company_id: str | None = None
    customer_id: str | None = None
    created_at: datetime


class ConnectionCreateRequest(BaseModel):
    source_system: str
    site_id: str
    display_name: str | None = None


class ConnectionResponse(BaseModel):
    connection_id: str
    tenant_id: str
    source_system: str
    site_id: str
    display_name: str | None = None
    status: ConnectionStatus
    created_at: datetime


class ConnectionListResponse(BaseModel):
    connections: list[ConnectionResponse] = Field(default_factory=list)


class ConnectorCheckpointSummary(BaseModel):
    entity_type: str
    watermark: str
    updated_at: datetime


class ConnectionHealthResponse(BaseModel):
    """INT-11: "Expose connection health, last successful sync, lag,
    record counts and error rates to operations." `lag_seconds` is honestly
    "time since this connection's own last checkpoint update," not "how
    far behind a real vendor's current state" — no real ingestion has ever
    run for any connection in this codebase yet (INT-05/INT-06 are
    blocked), so there is no vendor-side timestamp to compare against.
    `record_counts` doesn't exist as a concept here either: `ConnectorCheckpoint`
    tracks a watermark string per entity type, not a row count — reporting
    a fabricated count would be worse than omitting it.
    """

    connection_id: str
    status: ConnectionStatus
    checkpoints: list[ConnectorCheckpointSummary] = Field(default_factory=list)
    last_successful_sync: datetime | None = None
    lag_seconds: float | None = None
    dead_letters_unresolved: int
    dead_letters_total: int
