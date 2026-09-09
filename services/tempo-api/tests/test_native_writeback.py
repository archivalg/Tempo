"""Native writeback (app/maestro/native_writeback.py) — Standalone mode's
"the one vendor Tempo controls: itself." Checks the property that makes
this genuinely different from Phase E's NotImplementedWritebackClient:
for a tempo_native target, publish_roster and approve_leave really commit
to Tempo's own canonical tables, not a stubbed "unknown."

Also guards against the real bug caught while building this: publishing a
roster must *promote* the ShiftAssignment rows solve_named_roster already
wrote at status="proposed" to "committed", never insert a second row — an
early version doubled every published run's ShiftAssignment rows.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.models.canonical import Availability, ShiftAssignment

from .conftest import context_header
from .test_run_endpoint import VALID_REQUEST, WINDOW_START, _headers, _seed

NATIVE_TARGET = {"system": "tempo_native", "connection_id": "native", "site_id": "site_mel_01"}


def _execute(client, validated: dict, action_type: str, recommendation_id: str) -> dict:
    body = {
        "action_type": action_type,
        "recommendation_id": recommendation_id,
        "target": NATIVE_TARGET,
        "expected_source_version": None,
        "action_id": validated["action_id"],
        "action_token": validated["action_token"],
    }
    headers = context_header()
    headers["Idempotency-Key"] = str(uuid.uuid4())
    return client.post("/v1/actions", json=body, headers=headers)


def test_publish_roster_commits_proposed_rows_without_duplicating(client):
    _seed(client)
    run_resp = client.post("/v1/optimisations/named_roster", json=VALID_REQUEST, headers=_headers())
    recommendation_id = run_resp.json()["recommendation_id"]

    with client.session_local() as db:
        proposed = db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_test")).all()
        proposed_count = len(proposed)
        assert proposed_count > 0, "solve_named_roster should have written proposed ShiftAssignment rows"
        assert all(row.status == "proposed" for row in proposed)

    validate_req = {
        "action_type": "publish_roster", "recommendation_id": recommendation_id,
        "target": NATIVE_TARGET, "expected_source_version": None,
    }
    validated = client.post("/v1/actions/validate", json=validate_req, headers=context_header()).json()

    execute_resp = _execute(client, validated, "publish_roster", recommendation_id)
    assert execute_resp.status_code == 202
    body = execute_resp.json()
    assert body["status"] == "confirmed"
    assert f"{proposed_count} of {proposed_count}" in body["detail"]

    with client.session_local() as db:
        rows = db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_test")).all()
        assert len(rows) == proposed_count, "publishing must promote existing rows, never insert new ones"
        assert all(row.status == "committed" for row in rows)


def test_approve_leave_updates_availability_status(client):
    _seed(client)
    with client.session_local() as db:
        db.add(
            Availability(
                tenant_id="ten_test", worker_id="wrk_0",
                interval_start=WINDOW_START, interval_end=WINDOW_START + timedelta(hours=8),
                status="leave_requested", preference=1.0,
            )
        )
        db.commit()

    run_resp = client.post("/v1/optimisations/leave_rdo", json=VALID_REQUEST, headers=_headers())
    recommendation_id = run_resp.json()["recommendation_id"]

    validate_req = {
        "action_type": "approve_leave", "recommendation_id": recommendation_id,
        "target": NATIVE_TARGET, "expected_source_version": None,
    }
    validated = client.post("/v1/actions/validate", json=validate_req, headers=context_header()).json()
    execute_resp = _execute(client, validated, "approve_leave", recommendation_id)
    assert execute_resp.status_code == 202
    assert execute_resp.json()["status"] == "confirmed"

    with client.session_local() as db:
        row = db.scalar(select(Availability).where(Availability.tenant_id == "ten_test").where(Availability.worker_id == "wrk_0"))
        assert row.status == "leave"


def test_approve_leave_with_no_approved_requests_is_confirmed_not_rejected(client):
    """A severe staffing shortage can make leave_rdo approve nobody — that
    is a legitimate outcome, not a writeback failure, so applying zero
    approvals must report 'confirmed', never 'rejected'.
    """
    _seed(client)
    # No Availability leave/RDO request rows seeded at all -> leave_rdo's
    # own solve raises InsufficientData before an action is ever possible,
    # so instead simulate the "nothing approved" case directly against the
    # native client with a synthetic recommendation.
    from app.maestro.native_writeback import TempoNativeWritebackClient
    from app.models.runs import Recommendation

    with client.session_local() as db:
        db.add(
            Recommendation(
                recommendation_id="rec_no_approvals", run_id="run_no_approvals", tenant_id="ten_test",
                body={"run_type": "leave_rdo", "result": {"decisions": [{"worker_id": "wrk_0", "day": "2026-09-08", "request_type": "leave", "approved": False}]}, "explanation": {}},
                expires_at=None,
            )
        )
        db.commit()
        outcome = TempoNativeWritebackClient(db, "ten_test").submit("approve_leave", NATIVE_TARGET, {"recommendation_id": "rec_no_approvals"})

    assert outcome.status == "confirmed"
    assert "nothing to apply" in outcome.detail


def test_update_assignment_native_target_still_reports_unknown(client):
    """update_assignment has no defined native write target — disclosed,
    not guessed at — so even a tempo_native target must not fabricate a
    confirmation for it.
    """
    from datetime import timedelta as td

    from app.models.canonical import ActivityRoleZoneMap, ShiftAssignment as SA, SkillCertification, Worker, ZoneBacklog

    with client.session_local() as db:
        for index, zone in enumerate(["zone_a", "zone_a", "zone_b"]):
            db.add(Worker(worker_id=f"iw{index}", tenant_id="ten_test", employment_type="permanent", home_site="site_mel_01", status="active"))
            db.add(SkillCertification(tenant_id="ten_test", worker_id=f"iw{index}", skill_code="picker", valid_from=WINDOW_START - td(days=1), valid_to=None))
            db.add(SA(tenant_id="ten_test", worker_id=f"iw{index}", role="picker", zone=zone, start_at=WINDOW_START, end_at=WINDOW_START + td(hours=8), status="committed"))
        db.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id="site_mel_01", activity="picking", role="picker", zone="zone_a", weight=1.0))
        db.add(ActivityRoleZoneMap(tenant_id="ten_test", site_id="site_mel_01", activity="picking", role="picker", zone="zone_b", weight=1.0))
        db.add(ZoneBacklog(tenant_id="ten_test", site_id="site_mel_01", zone="zone_a", interval_start=WINDOW_START, backlog_units=3))
        db.add(ZoneBacklog(tenant_id="ten_test", site_id="site_mel_01", zone="zone_b", interval_start=WINDOW_START, backlog_units=0))
        db.commit()

    run_resp = client.post("/v1/optimisations/intraday_reallocation", json=VALID_REQUEST, headers=_headers())
    recommendation_id = run_resp.json()["recommendation_id"]

    validate_req = {
        "action_type": "update_assignment", "recommendation_id": recommendation_id,
        "target": NATIVE_TARGET, "expected_source_version": None,
    }
    validated = client.post("/v1/actions/validate", json=validate_req, headers=context_header()).json()
    execute_resp = _execute(client, validated, "update_assignment", recommendation_id)
    assert execute_resp.json()["status"] == "unknown"


def test_publish_roster_with_missing_recommendation_body_is_rejected(client):
    """Exercises the not-found path directly against the native client,
    since it can't be reached through the API (validate already 404s a
    missing recommendation) — this checks the writeback client's own
    defensiveness if ever called with a stale/deleted recommendation_id.
    """
    from app.maestro.native_writeback import TempoNativeWritebackClient

    with client.session_local() as db:
        outcome = TempoNativeWritebackClient(db, "ten_test").submit(
            "publish_roster", NATIVE_TARGET, {"recommendation_id": "rec_does_not_exist"}
        )
    assert outcome.status == "rejected"
