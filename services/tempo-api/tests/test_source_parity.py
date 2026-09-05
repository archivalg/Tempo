"""Source parity — Integration Spec AC-02: "The same golden scenario
produces equivalent business results from Tempo-native and third-party
canonical sources within defined tolerance." Also exercises DP-04 (the same
solver contract works regardless of source) concretely rather than just by
architectural assertion: app.solvers never imports app.maestro or checks
Worker.source_system, so this test is the actual proof.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.maestro.deputy.connector import DeputyConnector
from app.models.canonical import ActivityRoleZoneMap, DemandBucket, LabourCostRule, SkillCertification, Worker, WorkStandard
from app.schemas.runs import PlanningWindow, RunRequest, RunScope
from app.solvers.workforce_mix import solve_workforce_mix
from tests.test_deputy_connector import FakeDeputyClient

WINDOW_START = datetime(2026, 9, 8, tzinfo=timezone.utc)
SITE_ID = "site_mel_01"


def _seed_shared_config(session, tenant_id: str) -> None:
    """Everything that's tenant-governed configuration, not vendor-sourced
    data — identical for both tenants, matching the AI Labour Optimisation
    Spec's own note that WorkStandard/pay rules aren't captured from Deputy
    or UKG either.
    """
    for hours_back in range(4 * 24, 0, -1):
        session.add(
            DemandBucket(
                tenant_id=tenant_id,
                activity="picking",
                site_id=SITE_ID,
                customer_id=None,
                interval_start=WINDOW_START - timedelta(hours=hours_back),
                volume=50.0,
                source="tempo_native",
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


def _request(tenant_id: str) -> RunRequest:
    return RunRequest(
        request_id=f"req_{tenant_id}",
        scope=RunScope(tenant_id=tenant_id, site_ids=[SITE_ID], customer_ids=["cust_A"]),
        planning_window=PlanningWindow(
            start=WINDOW_START, end=datetime(2026, 9, 15, tzinfo=timezone.utc), timezone="Australia/Melbourne", bucket_minutes=60
        ),
    )


def test_workforce_mix_matches_between_tempo_native_and_deputy_sourced_workers(client):
    tenant_native = "ten_parity_native"
    tenant_deputy = "ten_parity_deputy"

    with client.session_local() as db:
        _seed_shared_config(db, tenant_native)
        _seed_shared_config(db, tenant_deputy)

        # Tempo-native: workers inserted directly, as Tempo's own capture would.
        for index, employment_type in enumerate(["permanent", "permanent", "permanent", "labour_hire"]):
            worker = Worker(worker_id=f"native_{index}", tenant_id=tenant_native, employment_type=employment_type, home_site=SITE_ID, status="active")
            db.add(worker)
            db.add(SkillCertification(tenant_id=tenant_native, worker_id=worker.worker_id, skill_code="picker", valid_from=WINDOW_START, valid_to=None))
        db.commit()

    # Deputy-sourced: the identical mix, pushed through the real connector pipeline.
    fake = FakeDeputyClient(
        employees=[
            {"Id": 1, "Active": True, "SubContractor": False},
            {"Id": 2, "Active": True, "SubContractor": False},
            {"Id": 3, "Active": True, "SubContractor": False},
            {"Id": 4, "Active": True, "SubContractor": True},
        ]
    )
    connector = DeputyConnector(fake, tenant_id=tenant_deputy, connection_id="con_parity", site_id=SITE_ID)
    with client.session_local() as db:
        summary = connector.backfill(db)
        db.commit()
        assert summary.rejected == 0 and summary.quarantined == 0

        deputy_workers = db.scalars(select(Worker).where(Worker.tenant_id == tenant_deputy)).all()
        # Deputy has no native "casual" concept in this mapping (§2.3 gap) —
        # give the Deputy-sourced workers the skill cert Tempo-native ones
        # already have, matching the same eligibility Deputy has no way to
        # express here either.
        for worker in deputy_workers:
            db.add(SkillCertification(tenant_id=tenant_deputy, worker_id=worker.worker_id, skill_code="picker", valid_from=WINDOW_START, valid_to=None))
        db.commit()

    with client.session_local() as db:
        native_outcome = solve_workforce_mix(db, tenant_native, [SITE_ID], _request(tenant_native))
    with client.session_local() as db:
        deputy_outcome = solve_workforce_mix(db, tenant_deputy, [SITE_ID], _request(tenant_deputy))

    native_cost = float(native_outcome.result["kpis"]["labour_cost"]["amount"])
    deputy_cost = float(deputy_outcome.result["kpis"]["labour_cost"]["amount"])
    assert native_outcome.result["kpis"]["coverage_pct"] == deputy_outcome.result["kpis"]["coverage_pct"]
    assert abs(native_cost - deputy_cost) < 0.01, f"native={native_cost} vs deputy={deputy_cost}"
