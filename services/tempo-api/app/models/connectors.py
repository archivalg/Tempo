"""Connector plumbing — Integration Spec §7.1: resumable checkpoints and a
dead-letter/quarantine queue with replay. Not part of the §6.1 canonical
model itself — these are Maestro's own operational tables, kept alongside
Tempo's canonical tables under the shared-store shortcut Phase 0/A already
disclosed (see services/tempo-api/README.md).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConnectorCheckpoint(Base):
    """Resumable watermark per (tenant, connection, entity type) — §7.1
    "Initial backfill by bounded date/window and resumable checkpoint" and
    "watermark-based delta polling".
    """

    __tablename__ = "connector_checkpoint"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    connection_id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String, primary_key=True)
    watermark: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class MaestroConnection(Base):
    """A tenant's declared connector instance — Phase F's "self-service
    onboarding" (§18), extended by Phase 3's credential lifecycle
    (INT-03/INT-04, app/api/v1/onboarding.py's .../credentials, .../test,
    .../activate, .../suspend, .../revoke endpoints):
    `pending_credentials` -> `credentials_stored` -> `active`, with
    `suspended`/`revoked` reachable from `active`.

    Registering a row, and moving it through this lifecycle, still does
    not trigger real ingestion: no OCI Vault exists in this environment
    (`app.maestro.credentials.InMemoryCredentialStore` is a disclosed,
    non-durable dev stand-in), no vendor sandbox credentials exist to
    validate against (INT-05/INT-06 are blocked for the same reason), and
    no scheduler exists yet to act on an `active` connection (Phase 4).
    `active` here means "administratively ready," not "actually
    syncing" — the same honesty `NotImplementedWritebackClient` applies to
    writeback outcomes.
    """

    __tablename__ = "maestro_connection"

    connection_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    source_system: Mapped[str] = mapped_column(String)
    site_id: Mapped[str] = mapped_column(String)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending_credentials")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ConnectorCredentialReference(Base):
    """INT-03/Appendix B's "Connector credential reference": "Connection,
    Vault secret reference, status and rotation metadata; no secret
    value." `vault_secret_reference` is the opaque reference
    `app.maestro.credentials.CredentialStore.store()` returns — genuinely
    never the secret itself, matching `MaestroConnection`'s docstring.
    One row per connection (composite would be redundant with the FK
    already being unique per connection — a connection has at most one
    live credential at a time; rotation replaces the reference in place
    and bumps `rotated_at`, it doesn't add a second row).
    """

    __tablename__ = "connector_credential_reference"

    connection_id: Mapped[str] = mapped_column(String, ForeignKey("maestro_connection.connection_id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    vault_secret_reference: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="stored")
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class IngestionDeadLetter(Base):
    """§7.1 "Dead-letter/quarantine queue with replay after mapping or
    source correction" and §6.3's quarantined/rejected data-quality states.
    """

    __tablename__ = "ingestion_dead_letter"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    source_system: Mapped[str] = mapped_column(String)
    connection_id: Mapped[str] = mapped_column(String)
    entity_type: Mapped[str] = mapped_column(String)
    event_id: Mapped[str] = mapped_column(String)
    quality_status: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    raw_envelope: Mapped[dict] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
