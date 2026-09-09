"""Run, evidence, audit and event tables — Integration Spec §6.1, §10, §13, §14.2."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class OptimisationRun(Base):
    """Immutable-once-completed run record (§6.1, §10, INT-005)."""

    __tablename__ = "optimisation_run"

    run_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    run_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="accepted")
    request: Mapped[dict] = mapped_column(JSON)
    snapshot_id: Mapped[str] = mapped_column(String)
    policy_version: Mapped[str | None] = mapped_column(String, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    explanation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    lineage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    supersedes_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendation"

    recommendation_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String, index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    body: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActionRequest(Base):
    """Phase E controlled action — §12's two-step contract. `status` follows
    Appendix C's action_status enum (validated/approved/submitted/confirmed/
    partially_confirmed/rejected/unknown/compensated) as a plain string, the
    same lightweight-not-a-DB-enum convention `OptimisationRun.status` uses.
    `payload_hash` is `app.core.idempotency.hash_payload` over
    (action_type, recommendation_id, target, expected_source_version) —
    reused, not reinvented, so validate and execute agree on one definition
    of "the same payload" (§12.2's "Execution requires... the same payload
    hash"). `action_token_hash` stores a hash of the issued token, never the
    token itself, so a leaked database row can't be replayed as a token.
    """

    __tablename__ = "action_request"

    action_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    recommendation_id: Mapped[str] = mapped_column(String, index=True)
    action_type: Mapped[str] = mapped_column(String)
    target: Mapped[dict] = mapped_column(JSON)
    expected_source_version: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_hash: Mapped[str] = mapped_column(String)
    action_token_hash: Mapped[str] = mapped_column(String)
    approver_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="validated")
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class SourceVersionWatermark(Base):
    """Tracks the source system's current version per (tenant, connection,
    site, resource) so §12.2's optimistic-concurrency check ("Any drift in
    source version... returns 409 and requires revalidation") has something
    real to compare `expected_source_version` against. Not a §6.1 canonical
    entity — Maestro's own operational state, same tier as
    `ConnectorCheckpoint` (app/models/connectors.py), which tracks the
    read-side equivalent (last-ingested watermark) rather than the
    write-side one this tracks.
    """

    __tablename__ = "source_version_watermark"

    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    connection_id: Mapped[str] = mapped_column(String, primary_key=True)
    site_id: Mapped[str] = mapped_column(String, primary_key=True)
    resource_type: Mapped[str] = mapped_column(String, primary_key=True)
    version: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class AuditRecord(Base):
    """§14.2 audit record."""

    __tablename__ = "audit_record"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    purpose: Mapped[str | None] = mapped_column(String, nullable=True)
    request_name: Mapped[str] = mapped_column(String)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    evidence_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EventRecord(Base):
    """Outbox table backing the in-process event bus (§13, §15.1 outbox pattern)."""

    __tablename__ = "event_record"

    event_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    event_type: Mapped[str] = mapped_column(String, index=True)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
