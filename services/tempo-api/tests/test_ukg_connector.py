"""UKG connector tests against a fake client (no HTTP) — mirrors
test_deputy_connector.py's coverage (worker-ref resolution ordering,
quarantine + replay, idempotent upsert, dead-lettering), parametrized
over both product-line source_system tags to prove the shared connector
algorithm behaves identically either way.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.maestro.ukg.connector import UkgConnector
from app.models.canonical import ShiftAssignment, Worker
from app.models.connectors import IngestionDeadLetter


class FakeUkgClient:
    def __init__(self, employees=None, punches=None, shifts=None, accruals=None):
        self._employees = employees or []
        self._punches = punches or []
        self._shifts = shifts or []
        self._accruals = accruals or []

    def list_employees(self, modified_since=None):
        return iter(self._employees)

    def list_punches(self, modified_since=None):
        return iter(self._punches)

    def list_shifts(self, modified_since=None):
        return iter(self._shifts)

    def list_accruals(self, modified_since=None):
        return iter(self._accruals)


@pytest.mark.parametrize("source_system", ["ukg_pro_wfm", "ukg_ready"])
def test_backfill_upserts_worker_then_resolves_punch(client, source_system):
    fake = FakeUkgClient(
        employees=[{"id": "501", "active": True, "employment_category": "Regular"}],
        punches=[{"id": "9001", "employee_id": "501", "start": "2026-09-01T06:00:00Z", "end": "2026-09-01T14:00:00Z", "approved": True}],
    )
    tenant_id = f"ten_ukg_{source_system}"
    connector = UkgConnector(fake, tenant_id=tenant_id, connection_id="con_1", site_id="site_mel_01", source_system=source_system)

    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()

        worker = db.scalar(select(Worker).where(Worker.tenant_id == tenant_id).where(Worker.source_ref == "501"))
        assert worker is not None
        assert worker.source_system == source_system

    assert summary.accepted + summary.accepted_with_warnings == 2
    assert summary.rejected == 0
    assert summary.quarantined == 0


def test_unknown_source_system_rejected():
    with pytest.raises(ValueError):
        UkgConnector(FakeUkgClient(), tenant_id="t", connection_id="c", site_id="s", source_system="not_a_real_ukg_line")


def test_shift_before_its_employee_is_quarantined_then_recovers_on_replay(client):
    fake = FakeUkgClient(shifts=[{"id": "s1", "employee_id": "999", "start": "2026-09-01T06:00:00Z", "end": "2026-09-01T14:00:00Z", "location_code": "42"}])
    connector = UkgConnector(fake, tenant_id="ten_ukg_ready", connection_id="con_1", site_id="site_mel_01", source_system="ukg_ready")

    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()
        assert summary.quarantined == 1
        dead_letters = db.scalars(select(IngestionDeadLetter).where(IngestionDeadLetter.tenant_id == "ten_ukg_ready")).all()
        assert len(dead_letters) == 1
        assert dead_letters[0].entity_type == "shift_assignment"

    fake2 = FakeUkgClient(
        employees=[{"id": "999", "active": True}],
        shifts=[{"id": "s1", "employee_id": "999", "start": "2026-09-01T06:00:00Z", "end": "2026-09-01T14:00:00Z", "location_code": "42"}],
    )
    connector2 = UkgConnector(fake2, tenant_id="ten_ukg_ready", connection_id="con_1", site_id="site_mel_01", source_system="ukg_ready")
    with client.session_local() as db:
        summary2 = connector2.backfill(db)
        db.commit()
        assert summary2.quarantined == 0
        shift = db.scalar(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_ukg_ready"))
        assert shift is not None
        assert shift.role == "general"  # unmapped location code falls back, doesn't silently drop the shift


def test_repeated_backfill_does_not_duplicate_rows(client):
    fake = FakeUkgClient(employees=[{"id": "501", "active": True}])
    connector = UkgConnector(fake, tenant_id="ten_ukg_pro_wfm", connection_id="con_1", site_id="site_mel_01", source_system="ukg_pro_wfm")

    with client.session_local() as db:
        connector.backfill(db)
        connector.backfill(db)
        db.commit()
        workers = db.scalars(select(Worker).where(Worker.tenant_id == "ten_ukg_pro_wfm")).all()
        assert len(workers) == 1


def test_rejected_record_is_dead_lettered_not_upserted(client):
    fake = FakeUkgClient(employees=[{"active": True}])  # missing id
    connector = UkgConnector(fake, tenant_id="ten_ukg_ready", connection_id="con_1", site_id="site_mel_01", source_system="ukg_ready")

    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()
        assert summary.rejected == 1
        assert db.scalars(select(Worker).where(Worker.tenant_id == "ten_ukg_ready")).all() == []
