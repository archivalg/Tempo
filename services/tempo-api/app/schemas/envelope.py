"""Canonical ingestion envelope (§6.2) and domain event envelope (§13.2)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DataQualityState = Literal["accepted", "accepted_with_warnings", "quarantined", "rejected", "superseded"]


class SourceRef(BaseModel):
    system: str
    connection_id: str
    record_id: str
    modified_at: datetime


class QualityInfo(BaseModel):
    status: DataQualityState
    warnings: list[str] = Field(default_factory=list)


class CanonicalEnvelope(BaseModel):
    """§6.2 — what a Maestro connector emits per ingested record.

    Phase 0 accepts these directly at /v1/canonical/ingest to prove the
    downstream pipeline (readiness, snapshotting, confidence) without a real
    Maestro connector; Phase B replaces the caller, not this contract.
    """

    schema_version: str = "1.0"
    event_id: str
    event_type: str
    occurred_at: datetime
    ingested_at: datetime
    tenant_id: str
    site_id: str
    source: SourceRef
    data: dict[str, Any]
    quality: QualityInfo


class DomainEvent(BaseModel):
    """§13.2 — CloudEvents-compatible envelope for the event catalogue in §13.1."""

    schema_version: str = "1.0"
    event_id: str
    event_type: str
    subject: str | None = None
    time: datetime
    correlation_id: str | None = None
    tenant_id: str
    payload: dict[str, Any]
