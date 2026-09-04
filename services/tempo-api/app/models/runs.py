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
    """Phase E (controlled action) — table defined now so the run/evidence
    schema doesn't need a breaking migration later; endpoints stay disabled
    until Phase E (see docs/roadmap.md and Integration Spec §12).
    """

    __tablename__ = "action_request"

    action_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    recommendation_id: Mapped[str] = mapped_column(String, index=True)
    approver_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scope: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String, default="validated")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


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
