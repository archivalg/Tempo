"""Gate 1 evidence: kiosk enrolment and abuse controls (blueprint §3.3, §5.1, acceptance matrix)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core import kiosk
from app.models.attendance import WorkerCredential
from app.models.canonical import Worker
from app.models.identity import KioskDevice, SecurityAuditEvent

from .conftest import context_header, enrol_kiosk

ADMIN = lambda **kw: context_header(roles=["tenant_admin"], **kw)  # noqa: E731


def _worker(client, wid="wrk_1", pin="1234", tenant="ten_test", site="site_mel_01"):
    with client.session_local() as s:
        s.add(Worker(worker_id=wid, tenant_id=tenant, employment_type="permanent", home_site=site, status="active"))
        s.flush()
        s.add(WorkerCredential(worker_id=wid, tenant_id=tenant, pin_hash=kiosk.hash_pin(pin)))
        s.commit()


def _clock(client, dev, wid="wrk_1", pin="1234", **extra):
    return client.post("/v1/attendance/whoami", json={"method": "pin", "worker_id": wid, "pin": pin, **extra}, headers=dev)


def test_pins_are_stored_as_argon2id_with_per_pin_salt(client):
    _worker(client, "a", "1234")
    _worker(client, "b", "1234")
    with client.session_local() as s:
        ha, hb = (s.get(WorkerCredential, w).pin_hash for w in ("a", "b"))
    assert ha.startswith("$argon2id$") and hb.startswith("$argon2id$") and ha != hb


def test_admin_enrols_device_via_api_and_code_is_single_use(client):
    r = client.post("/v1/devices", json={"name": "Dock 1", "site_ids": ["site_mel_01"]}, headers=ADMIN())
    assert r.status_code == 201
    code = r.json()["enrolment_code"]
    ok = client.post("/v1/kiosk/enrol", json={"enrolment_code": code})
    assert ok.status_code == 200 and ok.json()["device_credential"].startswith("tkd_")
    assert client.post("/v1/kiosk/enrol", json={"enrolment_code": code}).status_code == 401  # reuse
    listed = client.get("/v1/devices", headers=ADMIN()).json()
    assert listed[0]["status"] == "active" and listed[0]["enrolment_code"] is None
    with client.session_local() as s:
        d = s.scalar(select(KioskDevice))
        assert d.enrolment_code_digest is None and d.credential_reference.startswith("hmac-sha256:")
        assert "tkd_" not in d.credential_reference


def test_expired_and_forged_enrolment_codes_fail(client):
    enrol_kiosk(client)  # creates the tenant row
    with client.session_local() as s:
        d = KioskDevice(tenant_id="ten_test", site_ids=["site_mel_01"])
        s.add(d)
        s.flush()
        code = kiosk.new_enrolment_code(d)
        d.enrolment_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.commit()
    assert client.post("/v1/kiosk/enrol", json={"enrolment_code": code}).status_code == 401
    assert client.post("/v1/kiosk/enrol", json={"enrolment_code": "nope.nopenope1"}).status_code == 401


def test_admin_cannot_bind_device_beyond_own_sites_or_without_permission(client):
    r = client.post("/v1/devices", json={"name": "x", "site_ids": ["site_other"]}, headers=ADMIN())
    assert r.status_code == 400
    r = client.post("/v1/devices", json={"name": "x", "site_ids": ["site_mel_01"]}, headers=context_header(roles=["supervisor"]))
    assert r.status_code == 403


def test_disabled_device_and_tampered_credential_are_rejected(client):
    dev = enrol_kiosk(client)
    _worker(client)
    assert _clock(client, dev).status_code == 200
    bad = {"Authorization": dev["Authorization"][:-3] + "xyz"}
    assert _clock(client, bad).status_code == 401
    device_id = client.get("/v1/devices", headers=ADMIN()).json()[0]["device_id"]
    assert client.post(f"/v1/devices/{device_id}/disable", headers=ADMIN()).status_code == 200
    assert _clock(client, dev).status_code == 401


def test_kiosk_cannot_switch_tenant_or_site_by_any_request_input(client):
    dev = enrol_kiosk(client)
    _worker(client)
    _worker(client, "wrk_b", "9999", tenant="ten_b", site="site_b")
    forged = {**dev, "X-Tempo-Tenant": "ten_b", "X-Tempo-Context": '{"tenant_id":"ten_b"}'}
    assert _clock(client, forged, wid="wrk_b", pin="9999").status_code == 401  # other tenant's worker
    r = client.post("/v1/attendance/clock-in", json={"site_id": "site_b", "method": "pin", "worker_id": "wrk_1", "pin": "1234"}, headers=dev)
    assert r.status_code == 400  # site not enrolled on this device


def test_failed_pins_lock_the_worker_credential_and_audit(client):
    dev = enrol_kiosk(client)
    _worker(client)
    for _ in range(kiosk.WORKER_MAX_FAILS):
        assert _clock(client, dev, pin="0000").status_code == 401
    assert _clock(client, dev, pin="1234").status_code == 403  # correct PIN still refused while locked
    with client.session_local() as s:
        assert s.scalar(select(SecurityAuditEvent).where(SecurityAuditEvent.action == "kiosk.worker_locked"))


def test_unknown_worker_and_wrong_pin_are_indistinguishable(client):
    dev = enrol_kiosk(client)
    _worker(client)
    a = _clock(client, dev, wid="nobody", pin="1234")
    b = _clock(client, dev, wid="wrk_1", pin="0000")
    assert (a.status_code, a.json()["detail"]) == (b.status_code, b.json()["detail"])


def test_device_locks_after_many_failures(client):
    dev = enrol_kiosk(client)
    for i in range(kiosk.DEVICE_MAX_FAILS):
        _clock(client, dev, wid=f"ghost{i}", pin="1111")
    assert _clock(client, dev, wid="ghost", pin="1111").status_code == 403
    with client.session_local() as s:
        assert s.scalar(select(SecurityAuditEvent).where(SecurityAuditEvent.action == "kiosk.device_locked"))


def test_supervisor_token_cannot_be_used_as_a_kiosk(client):
    _worker(client)
    assert _clock(client, context_header(roles=["supervisor"])).status_code == 401


def test_suspended_tenant_stops_its_kiosks(client):
    from app.models.identity import Tenant

    dev = enrol_kiosk(client)
    _worker(client)
    assert _clock(client, dev).status_code == 200
    with client.session_local() as s:
        s.get(Tenant, "ten_test").status = "suspended"
        s.commit()
    assert _clock(client, dev).status_code == 401
