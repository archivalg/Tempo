"""Deputy connector — ties the client, mapping and canonical ingestion
together. Implements the §7.1 connector responsibilities this scaffold
covers: bounded backfill with a resumable checkpoint, idempotent upsert
(via app.core.ingestion), and dead-lettering on unmapped/invalid records.
Not covered here: real webhook signature verification and true
watermark-based delta polling beyond a plain 'now' timestamp — see
docs/roadmap.md.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ingestion import apply_canonical_envelope
from app.maestro.deputy.client import DeputyClient
from app.maestro.deputy.mapping import map_employee, map_leave, map_roster, map_timesheet
from app.models.canonical import Worker
from app.models.connectors import ConnectorCheckpoint


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


class DeputyConnector:
    def __init__(self, client: DeputyClient, tenant_id: str, connection_id: str, site_id: str):
        self.client = client
        self.tenant_id = tenant_id
        self.connection_id = connection_id
        self.site_id = site_id

    def _resolve_worker_ref(self, db: Session, source_ref: str) -> str | None:
        worker = db.scalar(
            select(Worker)
            .where(Worker.tenant_id == self.tenant_id)
            .where(Worker.source_system == "deputy")
            .where(Worker.source_ref == source_ref)
        )
        return worker.worker_id if worker else None

    def _checkpoint(self, db: Session, entity_type: str) -> str | None:
        row = db.get(ConnectorCheckpoint, (self.tenant_id, self.connection_id, entity_type))
        return row.watermark if row else None

    def _update_checkpoint(self, db: Session, entity_type: str, watermark: str) -> None:
        row = db.get(ConnectorCheckpoint, (self.tenant_id, self.connection_id, entity_type))
        if row is None:
            row = ConnectorCheckpoint(tenant_id=self.tenant_id, connection_id=self.connection_id, entity_type=entity_type, watermark=watermark)
            db.add(row)
        else:
            row.watermark = watermark
        db.flush()

    def _ingest(self, db: Session, summary: BackfillSummary, entity_type: str, envelope, fields: dict) -> None:
        if envelope.quality.status not in {"quarantined", "rejected"} and "_source_worker_ref" in fields:
            worker_id = self._resolve_worker_ref(db, fields.pop("_source_worker_ref"))
            if worker_id is None:
                envelope.quality.status = "quarantined"
                envelope.quality.warnings.append("referenced Employee not yet ingested as a canonical Worker")
            else:
                fields["worker_id"] = worker_id
        result = apply_canonical_envelope(db, envelope, entity_type, fields)
        summary.record(result.status, entity_type)

    def backfill(self, db: Session, modified_since: datetime | None = None) -> BackfillSummary:
        """Bounded backfill: employees first (so later resources can resolve
        worker_id), then timesheets/rosters/leave. §7.1's "initial backfill
        by bounded date/window" — pass modified_since to scope it; omit for
        a full historical pull.
        """
        summary = BackfillSummary()
        since_iso = modified_since.isoformat() if modified_since else self._checkpoint(db, "employee")

        for record in self.client.list_employees(modified_since=since_iso):
            envelope, entity_type, fields = map_employee(self.tenant_id, self.connection_id, self.site_id, record)
            self._ingest(db, summary, entity_type, envelope, fields)

        for record in self.client.list_timesheets(modified_since=since_iso):
            envelope, entity_type, fields = map_timesheet(self.tenant_id, self.connection_id, self.site_id, record)
            self._ingest(db, summary, entity_type, envelope, fields)

        for record in self.client.list_rosters(modified_since=since_iso):
            envelope, entity_type, fields = map_roster(self.tenant_id, self.connection_id, self.site_id, record)
            self._ingest(db, summary, entity_type, envelope, fields)

        for record in self.client.list_leave(modified_since=since_iso):
            envelope, entity_type, fields = map_leave(self.tenant_id, self.connection_id, self.site_id, record)
            self._ingest(db, summary, entity_type, envelope, fields)

        watermark = (modified_since or datetime.now(timezone.utc)).isoformat()
        for entity_type in ("employee", "attendance_session", "shift_assignment", "availability"):
            self._update_checkpoint(db, entity_type, watermark)

        return summary
