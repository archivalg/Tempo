"""Source parity — Integration Spec AC-02: "The same golden scenario
produces equivalent business results from Tempo-native and third-party
canonical sources within defined tolerance." Also exercises DP-04 (the same
solver contract works regardless of source) concretely rather than just by
architectural assertion: app.solvers never imports app.maestro or checks
Worker.source_system, so this test is the actual proof — across all three
connectors built so far (Deputy, UKG Pro WFM, UKG Ready).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.maestro.deputy.connector import DeputyConnector
from app.maestro.ukg.connector import UkgConnector
from app.models.canonical import ActivityRoleZoneMap, DemandBucket, LabourCostRule, SkillCertification, Worker, WorkStandard
from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.workforce_mix import solve_workforce_mix
from tests.test_deputy_connector import FakeDeputyClient
from tests.test_ukg_connector import FakeUkgClient

WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)
SITE_ID = "site_mel_01"

# Same underlying mix (3 "internal", 1 external/labour-hire) expressed
# through each source's own employment-type signal.
NATIVE_MIX = ["permanent", "permanent", "permanent", "labour_hire"]
DEPUTY_EMPLOYEES = [
    {"Id": 1, "Active": True, "SubContractor": False},
    {"Id": 2, "Active": True, "SubContractor": False},
    {"Id": 3, "Active": True, "SubContractor": False},
    {"Id": 4, "Active": True, "SubContractor": True},
]
UKG_EMPLOYEES = [
    {"id": "1", "active": True, "employment_category": "Regular"},
    {"id": "2", "active": True, "employment_category": "Regular"},
    {"id": "3", "active": True, "employment_category": "Regular"},
    {"id": "4", "active": True, "employment_category": "Contingent"},
]


def _seed_shared_config(session, tenant_id: str) -> None:
    """Everything that's tenant-governed configuration, not vendor-sourced
    data — identical across tenants, matching the AI Labour Optimisation
    Spec's own note that WorkStandard/pay rules aren't captured from Deputy
    or UKG either.
    """
    for hours_back in range(4 * 24, 0, -1):
        session.add(
            DemandBucket(
                tenant_id=tenant_id, activity="picking", site_id=SITE_ID, customer_id=None,
                interval_start=WINDOW_START - timedelta(hours=hours_back), volume=50.0, source="tempo_native",
            )
        )
    session.add(WorkStandard(tenant_id=tenant_id, activity="picking", complexity_segment=None, time_per_unit_seconds=45.0, effective_from=WINDOW_START - timedelta(days=365)))
    session.add(ActivityRoleZoneMap(tenant_id=tenant_id, site_id=SITE_ID, activity="picking", role="picker", zone="zone_a", weight=1.0))
    for labour_type, rate in [("permanent", "35.00"), ("labour_hire", "45.00")]:
        session.add(
            LabourCostRule(
                tenant_id=tenant_id, labour_type=labour_type, role="picker", rate=rate,
                overtime_multiplier="1.5", surcharge="10.00" if labour_type == "labour_hire" else None, currency="AUD",
            )
        )
    session.commit()


def _grant_skill_to_all_workers(session, tenant_id: str) -> None:
    workers = session.scalars(select(Worker).where(Worker.tenant_id == tenant_id)).all()
    for worker in workers:
        session.add(SkillCertification(tenant_id=tenant_id, worker_id=worker.worker_id, skill_code="picker", valid_from=WINDOW_START, valid_to=None))
    session.commit()


def _seed_native_workers(session, tenant_id: str) -> None:
    for index, employment_type in enumerate(NATIVE_MIX):
        session.add(Worker(worker_id=f"native_{index}", tenant_id=tenant_id, employment_type=employment_type, home_site=SITE_ID, status="active"))
    session.commit()
    _grant_skill_to_all_workers(session, tenant_id)


def _seed_deputy_workers(session, tenant_id: str) -> None:
    connector = DeputyConnector(FakeDeputyClient(employees=DEPUTY_EMPLOYEES), tenant_id=tenant_id, connection_id="con_parity", site_id=SITE_ID)
    summary = connector.backfill(session)
    session.commit()
    assert summary.rejected == 0 and summary.quarantined == 0
    _grant_skill_to_all_workers(session, tenant_id)


def _seed_ukg_workers(session, tenant_id: str, source_system: str) -> None:
    connector = UkgConnector(FakeUkgClient(employees=UKG_EMPLOYEES), tenant_id=tenant_id, connection_id="con_parity", site_id=SITE_ID, source_system=source_system)
    summary = connector.backfill(session)
    session.commit()
    assert summary.rejected == 0 and summary.quarantined == 0
    _grant_skill_to_all_workers(session, tenant_id)


def _request(tenant_id: str) -> RunRequest:
    return RunRequest(
        request_id=f"req_{tenant_id}",
        scope=RunScope(tenant_id=tenant_id, site_ids=[SITE_ID], customer_ids=["cust_A"]),
        planning_window=PlanningWindow(start=WINDOW_START, end=datetime(2026, 9, 15, tzinfo=timezone.utc), timezone="Australia/Melbourne", bucket_minutes=60),
    )


@pytest.mark.parametrize("source", ["deputy", "ukg_pro_wfm", "ukg_ready"])
def test_workforce_mix_matches_tempo_native_regardless_of_capture_source(client, source):
    tenant_native = f"ten_parity_native_{source}"
    tenant_other = f"ten_parity_{source}"

    with client.session_local() as db:
        _seed_shared_config(db, tenant_native)
        _seed_shared_config(db, tenant_other)
        _seed_native_workers(db, tenant_native)

    with client.session_local() as db:
        if source == "deputy":
            _seed_deputy_workers(db, tenant_other)
        else:
            _seed_ukg_workers(db, tenant_other, source_system=source)

    with client.session_local() as db:
        native_outcome = solve_workforce_mix(db, tenant_native, [SITE_ID], _request(tenant_native))
    with client.session_local() as db:
        other_outcome = solve_workforce_mix(db, tenant_other, [SITE_ID], _request(tenant_other))

    native_cost = float(native_outcome.result["kpis"]["labour_cost"]["amount"])
    other_cost = float(other_outcome.result["kpis"]["labour_cost"]["amount"])
    assert native_outcome.result["kpis"]["coverage_pct"] == other_outcome.result["kpis"]["coverage_pct"]
    assert abs(native_cost - other_cost) < 0.01, f"native={native_cost} vs {source}={other_cost}"
