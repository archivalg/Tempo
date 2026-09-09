"""Native capture — Business Spec §4/§5's Standalone "Time & Attendance
(native capture path)": PIN/NFC clock-in/out, optional GPS geofencing.
"""
from __future__ import annotations

from app.models.canonical import Worker

from .conftest import context_header


def _admin_header(**overrides):
    return context_header(roles=["tenant_admin"], **overrides)


def _kiosk_header(**overrides):
    # A physical kiosk isn't an RBAC principal — no roles required for
    # clock-in/out, matching app/api/v1/attendance.py's own reasoning.
    return context_header(roles=[], **overrides)


def _seed_worker(client, worker_id="wrk_1"):
    with client.session_local() as db:
        db.add(Worker(worker_id=worker_id, tenant_id="ten_test", employment_type="permanent", home_site="site_mel_01", status="active"))
        db.commit()


def test_enroll_then_clock_in_and_out_with_pin(client):
    _seed_worker(client)
    enroll = client.post("/v1/attendance/credentials", json={"worker_id": "wrk_1", "pin": "1234"}, headers=_admin_header())
    assert enroll.status_code == 201
    assert enroll.json() == {"worker_id": "wrk_1", "has_pin": True, "has_nfc": False}

    clock_in = client.post(
        "/v1/attendance/clock-in", json={"site_id": "site_mel_01", "method": "pin", "pin": "1234"}, headers=_kiosk_header()
    )
    assert clock_in.status_code == 200
    body = clock_in.json()
    assert body["worker_id"] == "wrk_1"
    assert body["geofence_status"] == "skipped"

    clock_out = client.post("/v1/attendance/clock-out", json={"method": "pin", "pin": "1234"}, headers=_kiosk_header())
    assert clock_out.status_code == 200
    assert clock_out.json()["duration_minutes"] >= 0


def test_second_clock_in_without_clocking_out_conflicts(client):
    _seed_worker(client)
    client.post("/v1/attendance/credentials", json={"worker_id": "wrk_1", "pin": "1234"}, headers=_admin_header())
    body = {"site_id": "site_mel_01", "method": "pin", "pin": "1234"}
    first = client.post("/v1/attendance/clock-in", json=body, headers=_kiosk_header())
    assert first.status_code == 200

    second = client.post("/v1/attendance/clock-in", json=body, headers=_kiosk_header())
    assert second.status_code == 409
    assert second.json()["error_code"] == "TEMPO-ATTENDANCE-001"


def test_clock_out_without_open_session_conflicts(client):
    _seed_worker(client)
    client.post("/v1/attendance/credentials", json={"worker_id": "wrk_1", "pin": "1234"}, headers=_admin_header())
    response = client.post("/v1/attendance/clock-out", json={"method": "pin", "pin": "1234"}, headers=_kiosk_header())
    assert response.status_code == 409
    assert response.json()["error_code"] == "TEMPO-ATTENDANCE-001"


def test_unrecognised_pin_rejected(client):
    _seed_worker(client)
    response = client.post(
        "/v1/attendance/clock-in", json={"site_id": "site_mel_01", "method": "pin", "pin": "0000"}, headers=_kiosk_header()
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "TEMPO-AUTH-001"


def test_clock_in_with_nfc(client):
    _seed_worker(client)
    client.post("/v1/attendance/credentials", json={"worker_id": "wrk_1", "nfc_tag_id": "tag-abc"}, headers=_admin_header())
    response = client.post(
        "/v1/attendance/clock-in", json={"site_id": "site_mel_01", "method": "nfc", "nfc_tag_id": "tag-abc"}, headers=_kiosk_header()
    )
    assert response.status_code == 200
    assert response.json()["worker_id"] == "wrk_1"


def test_geofence_violation_rejects_clock_in(client):
    _seed_worker(client)
    client.post("/v1/attendance/credentials", json={"worker_id": "wrk_1", "pin": "1234"}, headers=_admin_header())
    geofence = client.post(
        "/v1/site-geofences",
        json={"site_id": "site_mel_01", "latitude": -37.8136, "longitude": 144.9631, "radius_meters": 200},
        headers=_admin_header(),
    )
    assert geofence.status_code == 201

    within = client.post(
        "/v1/attendance/clock-in",
        json={"site_id": "site_mel_01", "method": "pin", "pin": "1234", "gps": {"latitude": -37.8136, "longitude": 144.9631}},
        headers=_kiosk_header(),
    )
    assert within.status_code == 200
    assert within.json()["geofence_status"] == "passed"
    client.post("/v1/attendance/clock-out", json={"method": "pin", "pin": "1234"}, headers=_kiosk_header())

    outside = client.post(
        "/v1/attendance/clock-in",
        json={"site_id": "site_mel_01", "method": "pin", "pin": "1234", "gps": {"latitude": -38.0, "longitude": 145.5}},
        headers=_kiosk_header(),
    )
    assert outside.status_code == 422
    assert outside.json()["error_code"] == "TEMPO-ATTENDANCE-002"


def test_credential_enrollment_requires_labour_configure(client):
    _seed_worker(client)
    response = client.post(
        "/v1/attendance/credentials", json={"worker_id": "wrk_1", "pin": "1234"}, headers=context_header(roles=["analyst"])
    )
    assert response.status_code == 403
    assert response.json()["error_code"] == "TEMPO-AUTH-002"


def test_get_worker_shifts_returns_committed_assignments(client):
    from datetime import timedelta

    from app.models.canonical import ShiftAssignment

    from .test_run_endpoint import WINDOW_START

    _seed_worker(client)
    with client.session_local() as db:
        db.add(
            ShiftAssignment(
                tenant_id="ten_test", worker_id="wrk_1", role="picker", zone="zone_a",
                start_at=WINDOW_START, end_at=WINDOW_START + timedelta(hours=8), status="committed",
            )
        )
        db.commit()

    response = client.get("/v1/workers/wrk_1/shifts", headers=context_header())
    assert response.status_code == 200
    shifts = response.json()
    assert len(shifts) == 1
    assert shifts[0]["role"] == "picker"


def test_get_shifts_for_unknown_worker_not_found(client):
    response = client.get("/v1/workers/wrk_does_not_exist/shifts", headers=context_header())
    assert response.status_code == 404
