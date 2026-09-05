"""Seeds a small but realistic canonical dataset so Phase A solver tests
exercise the real pipeline (Holt forecast -> labour requirement -> MILP mix
-> CP-SAT roster) instead of stub output.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.models.canonical import (
    ActivityRoleZoneMap,
    DemandBucket,
    LabourCostRule,
    SkillCertification,
    Worker,
    WorkStandard,
)

ACTIVITY = "picking"
ROLE = "picker"
ZONE = "zone_a"


def seed_named_roster_scenario(session, tenant_id: str, site_id: str, window_start: datetime) -> None:
    # Flat history on purpose: Holt's method has no seasonal term, so a
    # sawtooth day/night pattern here would leak into the trend estimate
    # right at the forecast boundary and either inflate or (worse) zero out
    # the week-long forecast depending on where the cutover happened to
    # land in the cycle. A stable series keeps this fixture's story about
    # the solvers, not about Holt's known blind spot for seasonality.
    for hours_back in range(4 * 24, 0, -1):
        interval_start = window_start - timedelta(hours=hours_back)
        session.add(
            DemandBucket(
                tenant_id=tenant_id,
                activity=ACTIVITY,
                site_id=site_id,
                customer_id=None,
                interval_start=interval_start,
                volume=50.0,
                source="tempo_native",
            )
        )

    session.add(
        WorkStandard(
            tenant_id=tenant_id,
            activity=ACTIVITY,
            complexity_segment=None,
            time_per_unit_seconds=45.0,
            effective_from=window_start - timedelta(days=365),
        )
    )
    session.add(
        ActivityRoleZoneMap(tenant_id=tenant_id, site_id=site_id, activity=ACTIVITY, role=ROLE, zone=ZONE, weight=1.0)
    )

    employment_types = ["permanent", "permanent", "casual", "casual", "labour_hire"]
    for index, employment_type in enumerate(employment_types):
        worker = Worker(
            worker_id=f"wrk_{index}",
            tenant_id=tenant_id,
            employment_type=employment_type,
            home_site=site_id,
            status="active",
        )
        session.add(worker)
        session.add(
            SkillCertification(
                tenant_id=tenant_id,
                worker_id=worker.worker_id,
                skill_code=ROLE,
                valid_from=window_start - timedelta(days=365),
                valid_to=None,
            )
        )

    rates = {"permanent": ("35.00", "1.5", None), "casual": ("32.00", "1.5", None), "labour_hire": ("45.00", "1.0", "10.00")}
    for labour_type, (rate, ot_multiplier, surcharge) in rates.items():
        session.add(
            LabourCostRule(
                tenant_id=tenant_id,
                labour_type=labour_type,
                role=ROLE,
                rate=rate,
                overtime_multiplier=ot_multiplier,
                surcharge=surcharge,
                currency="AUD",
            )
        )

    session.commit()
