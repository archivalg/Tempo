"""Tests the Deputy connector end to end against a fake DeputyClient (no
HTTP) — mapping, worker_ref resolution ordering, idempotent upsert, and
dead-lettering of unresolvable/invalid records.
"""
from __future__ import annotations

from sqlalchemy import select

from app.maestro.deputy.connector import DeputyConnector
from app.models.canonical import AttendanceSession, ShiftAssignment, Worker
from app.models.connectors import IngestionDeadLetter


class FakeDeputyClient:
    def __init__(self, employees=None, timesheets=None, rosters=None, leave=None):
        self._employees = employees or []
        self._timesheets = timesheets or []
        self._rosters = rosters or []
        self._leave = leave or []

    def list_employees(self, modified_since=None):
        return iter(self._employees)

    def list_timesheets(self, modified_since=None):
        return iter(self._timesheets)

    def list_rosters(self, modified_since=None):
        return iter(self._rosters)

    def list_leave(self, modified_since=None):
        return iter(self._leave)


def test_backfill_upserts_worker_then_resolves_timesheet(client):
    fake = FakeDeputyClient(
        employees=[{"Id": 501, "Active": True, "Modified": "2026-09-01T00:00:00Z"}],
        timesheets=[{"Id": 9001, "Employee": 501, "StartTime": "2026-09-01T06:00:00Z", "EndTime": "2026-09-01T14:00:00Z", "Approved": True}],
    )
    connector = DeputyConnector(fake, tenant_id="ten_deputy", connection_id="con_1", site_id="site_mel_01")

    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()

        worker = db.scalar(select(Worker).where(Worker.tenant_id == "ten_deputy").where(Worker.source_ref == "501"))
        assert worker is not None
        assert worker.employment_type == "permanent"

        session_row = db.scalar(select(AttendanceSession).where(AttendanceSession.tenant_id == "ten_deputy"))
        assert session_row is not None
        assert session_row.worker_id == worker.worker_id

    assert summary.accepted + summary.accepted_with_warnings == 2
    assert summary.rejected == 0
    assert summary.quarantined == 0


def test_timesheet_before_its_employee_is_quarantined_then_recovers_on_replay(client):
    fake = FakeDeputyClient(
        timesheets=[{"Id": 9002, "Employee": 999, "StartTime": "2026-09-01T06:00:00Z", "EndTime": "2026-09-01T14:00:00Z"}],
    )
    connector = DeputyConnector(fake, tenant_id="ten_deputy", connection_id="con_1", site_id="site_mel_01")

    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()
        assert summary.quarantined == 1
        dead_letters = db.scalars(select(IngestionDeadLetter).where(IngestionDeadLetter.tenant_id == "ten_deputy")).all()
        assert len(dead_letters) == 1
        assert dead_letters[0].entity_type == "attendance_session"

    # Employee arrives later — replaying the same timesheet now resolves cleanly.
    fake2 = FakeDeputyClient(
        employees=[{"Id": 999, "Active": True}],
        timesheets=[{"Id": 9002, "Employee": 999, "StartTime": "2026-09-01T06:00:00Z", "EndTime": "2026-09-01T14:00:00Z"}],
    )
    connector2 = DeputyConnector(fake2, tenant_id="ten_deputy", connection_id="con_1", site_id="site_mel_01")
    with client.session_local() as db:
        summary2 = connector2.backfill(db)
        db.commit()
        assert summary2.quarantined == 0
        session_row = db.scalar(select(AttendanceSession).where(AttendanceSession.tenant_id == "ten_deputy"))
        assert session_row is not None


def test_repeated_backfill_of_same_records_does_not_duplicate_rows(client):
    fake = FakeDeputyClient(
        employees=[{"Id": 501, "Active": True}],
        rosters=[{"Id": 7001, "Employee": 501, "StartTime": "2026-09-01T06:00:00Z", "EndTime": "2026-09-01T14:00:00Z", "OperationalUnit": "42"}],
    )
    connector = DeputyConnector(fake, tenant_id="ten_deputy", connection_id="con_1", site_id="site_mel_01")

    with client.session_local() as db:
        connector.backfill(db)
        connector.backfill(db)
        db.commit()
        workers = db.scalars(select(Worker).where(Worker.tenant_id == "ten_deputy")).all()
        shifts = db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_deputy")).all()
        assert len(workers) == 1
        assert len(shifts) == 1
        assert shifts[0].role == "general"  # unmapped OperationalUnit falls back, doesn't silently drop the shift


def test_rejected_record_is_dead_lettered_not_upserted(client):
    fake = FakeDeputyClient(employees=[{"Active": True}])  # missing Id
    connector = DeputyConnector(fake, tenant_id="ten_deputy", connection_id="con_1", site_id="site_mel_01")

    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()
        assert summary.rejected == 1
        assert db.scalars(select(Worker).where(Worker.tenant_id == "ten_deputy")).all() == []
