"""WMS connector tests against a fake client (no HTTP) — mirrors the
Deputy/UKG connector tests' coverage (idempotent upsert, dead-lettering)
minus the worker-ref resolution step, which backlog snapshots don't need.
"""
from __future__ import annotations

from sqlalchemy import select

from app.maestro.wms.connector import WmsConnector
from app.models.canonical import ZoneBacklog
from app.models.connectors import IngestionDeadLetter


class FakeWmsClient:
    def __init__(self, snapshots=None):
        self._snapshots = snapshots or []

    def list_backlog_snapshots(self, modified_since=None):
        return iter(self._snapshots)


def test_backfill_upserts_backlog_snapshot(client):
    fake = FakeWmsClient(
        snapshots=[{"id": "b1", "zone": "zone_a", "intervalStart": "2026-09-08T00:00:00Z", "backlogUnits": 12.5}]
    )
    connector = WmsConnector(fake, tenant_id="ten_wms", connection_id="con_1", site_id="site_mel_01")

    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()

        row = db.scalar(select(ZoneBacklog).where(ZoneBacklog.tenant_id == "ten_wms").where(ZoneBacklog.source_ref == "b1"))
        assert row is not None
        assert row.zone == "zone_a"
        assert row.backlog_units == 12.5

    assert summary.accepted == 1
    assert summary.rejected == 0


def test_repeated_backfill_does_not_duplicate_rows(client):
    fake = FakeWmsClient(
        snapshots=[{"id": "b1", "zone": "zone_a", "intervalStart": "2026-09-08T00:00:00Z", "backlogUnits": 5.0}]
    )
    connector = WmsConnector(fake, tenant_id="ten_wms", connection_id="con_1", site_id="site_mel_01")

    with client.session_local() as db:
        connector.backfill(db)
        connector.backfill(db)
        db.commit()
        rows = db.scalars(select(ZoneBacklog).where(ZoneBacklog.tenant_id == "ten_wms")).all()
        assert len(rows) == 1


def test_updated_snapshot_overwrites_previous_value(client):
    connector = WmsConnector(
        FakeWmsClient(snapshots=[{"id": "b1", "zone": "zone_a", "intervalStart": "2026-09-08T00:00:00Z", "backlogUnits": 5.0}]),
        tenant_id="ten_wms", connection_id="con_1", site_id="site_mel_01",
    )
    with client.session_local() as db:
        connector.backfill(db)
        db.commit()

    connector2 = WmsConnector(
        FakeWmsClient(snapshots=[{"id": "b1", "zone": "zone_a", "intervalStart": "2026-09-08T00:00:00Z", "backlogUnits": 9.0}]),
        tenant_id="ten_wms", connection_id="con_1", site_id="site_mel_01",
    )
    with client.session_local() as db:
        connector2.backfill(db)
        db.commit()
        row = db.scalar(select(ZoneBacklog).where(ZoneBacklog.tenant_id == "ten_wms").where(ZoneBacklog.source_ref == "b1"))
        assert row.backlog_units == 9.0


def test_negative_backlog_is_clamped_with_warning(client):
    connector = WmsConnector(
        FakeWmsClient(snapshots=[{"id": "b1", "zone": "zone_a", "intervalStart": "2026-09-08T00:00:00Z", "backlogUnits": -3.0}]),
        tenant_id="ten_wms", connection_id="con_1", site_id="site_mel_01",
    )
    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()
        row = db.scalar(select(ZoneBacklog).where(ZoneBacklog.tenant_id == "ten_wms").where(ZoneBacklog.source_ref == "b1"))
        assert row.backlog_units == 0.0

    assert summary.accepted_with_warnings == 1


def test_rejected_record_is_dead_lettered_not_upserted(client):
    connector = WmsConnector(FakeWmsClient(snapshots=[{"zone": "zone_a"}]), tenant_id="ten_wms", connection_id="con_1", site_id="site_mel_01")  # missing id/backlogUnits/intervalStart

    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()
        assert summary.rejected == 1
        assert db.scalars(select(ZoneBacklog).where(ZoneBacklog.tenant_id == "ten_wms")).all() == []
        dead_letters = db.scalars(select(IngestionDeadLetter).where(IngestionDeadLetter.tenant_id == "ten_wms")).all()
        assert len(dead_letters) == 1
