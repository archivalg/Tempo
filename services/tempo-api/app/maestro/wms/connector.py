"""WMS connector — populates ZoneBacklog for Intraday Reallocation.

Simpler than Deputy/UKG's connectors: a backlog snapshot isn't tied to a
worker, so there's no FK-resolution/quarantine-until-dependency-arrives
step here — every valid record ingests standalone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.ingestion import apply_canonical_envelope
from app.maestro.wms.mapping import map_backlog_snapshot
from app.models.connectors import ConnectorCheckpoint


class WmsApiClient(Protocol):
    def list_backlog_snapshots(self, modified_since: str | None = None): ...


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


class WmsConnector:
    def __init__(self, client: WmsApiClient, tenant_id: str, connection_id: str, site_id: str):
        self.client = client
        self.tenant_id = tenant_id
        self.connection_id = connection_id
        self.site_id = site_id

    def _checkpoint(self, db: Session) -> str | None:
        row = db.get(ConnectorCheckpoint, (self.tenant_id, self.connection_id, "zone_backlog"))
        return row.watermark if row else None

    def _update_checkpoint(self, db: Session, watermark: str) -> None:
        row = db.get(ConnectorCheckpoint, (self.tenant_id, self.connection_id, "zone_backlog"))
        if row is None:
            db.add(ConnectorCheckpoint(tenant_id=self.tenant_id, connection_id=self.connection_id, entity_type="zone_backlog", watermark=watermark))
        else:
            row.watermark = watermark
        db.flush()

    def backfill(self, db: Session, modified_since: datetime | None = None) -> BackfillSummary:
        summary = BackfillSummary()
        since_iso = modified_since.isoformat() if modified_since else self._checkpoint(db)

        for record in self.client.list_backlog_snapshots(modified_since=since_iso):
            envelope, entity_type, fields = map_backlog_snapshot(self.tenant_id, self.connection_id, self.site_id, record)
            result = apply_canonical_envelope(db, envelope, entity_type, fields)
            summary.record(result.status, entity_type)

        self._update_checkpoint(db, (modified_since or datetime.now(timezone.utc)).isoformat())
        return summary
