"""Self-service onboarding contracts — Phase F (§18)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ConnectionStatus = Literal["pending_credentials", "disabled"]


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
