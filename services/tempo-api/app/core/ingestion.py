"""Applies a canonical envelope (§6.2) to Tempo's canonical store.

This is the one place that turns "a record a connector produced" into
either an upsert against a canonical table or a dead-lettered record —
every connector (Deputy today, UKG later) calls this instead of writing to
canonical tables itself, so the upsert-idempotency and quarantine rules in
§6.3/§7.1 are enforced once, not per-connector.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.events import event_bus
from app.models.canonical import Availability, AttendanceSession, ShiftAssignment, Worker
from app.models.connectors import IngestionDeadLetter
from app.schemas.envelope import CanonicalEnvelope


@dataclass
class IngestionResult:
    status: str  # accepted | accepted_with_warnings | quarantined | rejected
    entity_id: str | None = None


def _upsert_worker(db: Session, tenant_id: str, source_system: str, source_ref: str, fields: dict[str, Any]) -> Worker:
    existing = db.scalar(
        select(Worker)
        .where(Worker.tenant_id == tenant_id)
        .where(Worker.source_system == source_system)
        .where(Worker.source_ref == source_ref)
    )
    if existing is None:
        existing = Worker(tenant_id=tenant_id, source_system=source_system, source_ref=source_ref)
        db.add(existing)
    for key, value in fields.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def _upsert_attendance_session(
    db: Session, tenant_id: str, source_system: str, source_ref: str, fields: dict[str, Any]
) -> AttendanceSession:
    existing = db.scalar(
        select(AttendanceSession)
        .where(AttendanceSession.tenant_id == tenant_id)
        .where(AttendanceSession.source_system == source_system)
        .where(AttendanceSession.source_ref == source_ref)
    )
    if existing is None:
        existing = AttendanceSession(tenant_id=tenant_id, source_system=source_system, source_ref=source_ref)
        db.add(existing)
    for key, value in fields.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def _upsert_shift_assignment(
    db: Session, tenant_id: str, source_system: str, source_ref: str, fields: dict[str, Any]
) -> ShiftAssignment:
    existing = db.scalar(
        select(ShiftAssignment)
        .where(ShiftAssignment.tenant_id == tenant_id)
        .where(ShiftAssignment.source_system == source_system)
        .where(ShiftAssignment.source_ref == source_ref)
    )
    if existing is None:
        existing = ShiftAssignment(tenant_id=tenant_id, source_system=source_system, source_ref=source_ref)
        db.add(existing)
    for key, value in fields.items():
        setattr(existing, key, value)
    db.flush()
    return existing


def _upsert_availability(
    db: Session, tenant_id: str, source_system: str, source_ref: str, fields: dict[str, Any]
) -> Availability:
    existing = db.scalar(
        select(Availability)
        .where(Availability.tenant_id == tenant_id)
        .where(Availability.source_system == source_system)
        .where(Availability.source_ref == source_ref)
    )
    if existing is None:
        existing = Availability(tenant_id=tenant_id, source_system=source_system, source_ref=source_ref)
        db.add(existing)
    for key, value in fields.items():
        setattr(existing, key, value)
    db.flush()
    return existing


_UPSERT_BY_ENTITY = {
    "worker": _upsert_worker,
    "attendance_session": _upsert_attendance_session,
    "shift_assignment": _upsert_shift_assignment,
    "availability": _upsert_availability,
}


def apply_canonical_envelope(db: Session, envelope: CanonicalEnvelope, entity_type: str, fields: dict[str, Any]) -> IngestionResult:
    """`entity_type` names one of _UPSERT_BY_ENTITY's keys; `fields` are the
    already-mapped canonical column values a connector's mapping module
    produced (see app/maestro/deputy/mapping.py for the Deputy case).
    """
    tenant_id = envelope.tenant_id
    source_system = envelope.source.system
    source_ref = envelope.source.record_id

    if envelope.quality.status in {"quarantined", "rejected"}:
        db.add(
            IngestionDeadLetter(
                tenant_id=tenant_id,
                source_system=source_system,
                connection_id=envelope.source.connection_id,
                entity_type=entity_type,
                event_id=envelope.event_id,
                quality_status=envelope.quality.status,
                reason="; ".join(envelope.quality.warnings) or envelope.quality.status,
                raw_envelope=envelope.model_dump(mode="json"),
            )
        )
        db.flush()
        event_bus.publish(
            db,
            tenant_id,
            "canonical.data.quarantined",
            {"entity_type": entity_type, "source": source_system, "record_id": source_ref, "status": envelope.quality.status},
            subject=source_ref,
        )
        return IngestionResult(status=envelope.quality.status)

    upsert = _UPSERT_BY_ENTITY.get(entity_type)
    if upsert is None:
        raise ValueError(f"no canonical upsert registered for entity_type '{entity_type}'")
    row = upsert(db, tenant_id, source_system, source_ref, fields)

    event_bus.publish(
        db,
        tenant_id,
        "canonical.data.updated",
        {"entity_type": entity_type, "source": source_system, "record_id": source_ref},
        subject=source_ref,
    )
    return IngestionResult(status=envelope.quality.status, entity_id=getattr(row, "worker_id", None) or getattr(row, "id", None) or getattr(row, "shift_id", None))
