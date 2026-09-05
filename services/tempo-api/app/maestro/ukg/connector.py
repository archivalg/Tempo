"""UKG connector — one algorithm, either product-line client.

This is the concrete answer to the spec's "UKG is not one API... detect
and configure per product line at tenant onboarding" (§2.2): onboarding
picks which client to construct (UkgProWfmClient or UkgReadyClient) and
passes its `SOURCE_SYSTEM` tag; everything below — pagination already
handled by the client, mapping, worker-ref resolution, checkpointing,
dead-lettering — is identical either way, matching DP-04 (the same
contract works regardless of source) one level below the solver boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ingestion import apply_canonical_envelope
from app.maestro.ukg.mapping import map_employee, map_leave, map_punch, map_shift
from app.models.canonical import Worker
from app.models.connectors import ConnectorCheckpoint


class UkgApiClient(Protocol):
    def list_employees(self, modified_since: str | None = None): ...
    def list_punches(self, modified_since: str | None = None): ...
    def list_shifts(self, modified_since: str | None = None): ...
    def list_accruals(self, modified_since: str | None = None): ...


@dataclass
class BackfillSummary:
    accepted: int = 0
    accepted_with_warnings: int = 0
    quarantined: int = 0
    rejected: int = 0
    by_entity: dict[str, int] = field(default_factory=dict)

    def record(self, status: str, entity_type: str) -> None:
        setattr(self, status, getattr(self, status) + 1)
        self.by_entity[entity_type] = self.by_entity.get(entity_type, 0) + 1


class UkgConnector:
    def __init__(self, client: UkgApiClient, tenant_id: str, connection_id: str, site_id: str, source_system: str):
        if source_system not in {"ukg_pro_wfm", "ukg_ready"}:
            raise ValueError(f"unknown UKG source_system '{source_system}' — expected ukg_pro_wfm or ukg_ready")
        self.client = client
        self.tenant_id = tenant_id
        self.connection_id = connection_id
        self.site_id = site_id
        self.source_system = source_system

    def _resolve_worker_ref(self, db: Session, source_ref: str) -> str | None:
        worker = db.scalar(
            select(Worker)
            .where(Worker.tenant_id == self.tenant_id)
            .where(Worker.source_system == self.source_system)
            .where(Worker.source_ref == source_ref)
        )
        return worker.worker_id if worker else None

    def _checkpoint(self, db: Session, entity_type: str) -> str | None:
        row = db.get(ConnectorCheckpoint, (self.tenant_id, self.connection_id, entity_type))
        return row.watermark if row else None

    def _update_checkpoint(self, db: Session, entity_type: str, watermark: str) -> None:
        row = db.get(ConnectorCheckpoint, (self.tenant_id, self.connection_id, entity_type))
        if row is None:
            db.add(ConnectorCheckpoint(tenant_id=self.tenant_id, connection_id=self.connection_id, entity_type=entity_type, watermark=watermark))
        else:
            row.watermark = watermark
        db.flush()

    def _ingest(self, db: Session, summary: BackfillSummary, entity_type: str, envelope, fields: dict) -> None:
        if envelope.quality.status not in {"quarantined", "rejected"} and "_source_worker_ref" in fields:
            worker_id = self._resolve_worker_ref(db, fields.pop("_source_worker_ref"))
            if worker_id is None:
                envelope.quality.status = "quarantined"
                envelope.quality.warnings.append("referenced employee not yet ingested as a canonical Worker")
            else:
                fields["worker_id"] = worker_id
        result = apply_canonical_envelope(db, envelope, entity_type, fields)
        summary.record(result.status, entity_type)

    def backfill(self, db: Session, modified_since: datetime | None = None) -> BackfillSummary:
        summary = BackfillSummary()
        since_iso = modified_since.isoformat() if modified_since else self._checkpoint(db, "employee")

        for record in self.client.list_employees(modified_since=since_iso):
            envelope, entity_type, fields = map_employee(self.tenant_id, self.connection_id, self.source_system, self.site_id, record)
            self._ingest(db, summary, entity_type, envelope, fields)

        for record in self.client.list_punches(modified_since=since_iso):
            envelope, entity_type, fields = map_punch(self.tenant_id, self.connection_id, self.source_system, self.site_id, record)
            self._ingest(db, summary, entity_type, envelope, fields)

        for record in self.client.list_shifts(modified_since=since_iso):
            envelope, entity_type, fields = map_shift(self.tenant_id, self.connection_id, self.source_system, self.site_id, record)
            self._ingest(db, summary, entity_type, envelope, fields)

        for record in self.client.list_accruals(modified_since=since_iso):
            envelope, entity_type, fields = map_leave(self.tenant_id, self.connection_id, self.source_system, self.site_id, record)
            self._ingest(db, summary, entity_type, envelope, fields)

        watermark = (modified_since or datetime.now(timezone.utc)).isoformat()
        for entity_type in ("employee", "attendance_session", "shift_assignment", "availability"):
            self._update_checkpoint(db, entity_type, watermark)

        return summary
