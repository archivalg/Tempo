"""Proves intraday_reallocation works against backlog ingested through the
real WMS connector pipeline, not just directly-seeded ZoneBacklog rows —
closing the loop this codebase has followed for every other solver/
connector pair (e.g. tests/test_source_parity.py for Deputy/UKG).
"""
from __future__ import annotations

from datetime import timedelta

from app.maestro.wms.connector import WmsConnector
from app.models.canonical import ActivityRoleZoneMap, ShiftAssignment, SkillCertification, Worker
from app.solvers.intraday_reallocation import solve_intraday_reallocation
from .test_intraday_reallocation import SITE_ID, WINDOW_START, _request
from .test_wms_connector import FakeWmsClient


def test_intraday_reallocation_solves_correctly_against_wms_ingested_backlog(client):
    with client.session_local() as db:
        for index, zone in enumerate(["zone_a", "zone_a", "zone_b"]):
            db.add(Worker(worker_id=f"w{index}", tenant_id="ten_test", employment_type="permanent", home_site=SITE_ID, status="active"))
            db.add(
                SkillCertification(tenant_id="ten_test", worker_id=f"w{index}", skill_code="picker", valid_from=WINDOW_START - timedelta(days=1), valid_to=None)
            )
            db.add(
                ShiftAssignment(
                    tenant_id="ten_test", worker_id=f"w{index}", role="picker", zone=zone,
                    start_at=WINDOW_START, end_at=WINDOW_START + timedelta(hours=8), status="committed",
                )
            )
        db.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id=SITE_ID, activity="picking", role="picker", zone="zone_a", weight=1.0))
        db.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id=SITE_ID, activity="picking", role="picker", zone="zone_b", weight=1.0))
        db.commit()

        # Backlog arrives through the real WMS connector, not a direct insert.
        connector = WmsConnector(
            FakeWmsClient(
                snapshots=[
                    {"id": "snap-a", "zone": "zone_a", "intervalStart": WINDOW_START.isoformat(), "backlogUnits": 3},
                    {"id": "snap-b", "zone": "zone_b", "intervalStart": WINDOW_START.isoformat(), "backlogUnits": 0},
                ]
            ),
            tenant_id="ten_test", connection_id="con_wms", site_id=SITE_ID,
        )
        summary = connector.backfill(db)
        db.commit()
        assert summary.rejected == 0

        outcome = solve_intraday_reallocation(db, "ten_test", [SITE_ID], _request())

    by_worker = {r["worker_id"]: r for r in outcome.result["reassignments"]}
    assert by_worker["w2"]["moved"] is True
    assert by_worker["w2"]["to_zone"] == "zone_a"
    assert outcome.result["kpis"]["remaining_backlog"] == 0
