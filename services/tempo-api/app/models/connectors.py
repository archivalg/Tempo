"""Connector plumbing — Integration Spec §7.1: resumable checkpoints and a
dead-letter/quarantine queue with replay. Not part of the §6.1 canonical
model itself — these are Maestro's own operational tables, kept alongside
Tempo's canonical tables under the shared-store shortcut Phase 0/A already
disclosed (see services/tempo-api/README.md).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, String
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
