"""Roadmap M6-ONBOARD (operational part): resumable guided setup — state survives, steps are read from real data, retries never duplicate."""
from __future__ import annotations

from sqlalchemy import select

from app.models.billing import TenantSetup
from app.models.directory import Site
from app.models.identity import Tenant

from .conftest import context_header

ADMIN = lambda **kw: context_header(roles=["tenant_admin"], user_id="usr_admin", site_ids=["syd_1", "mel_1"], **kw)  # noqa: E731


def seed_tenant(client):
    with client.session_local() as s:
        if s.get(Tenant, "ten_test") is None:
            s.add(Tenant(tenant_id="ten_test", name="Test Co"))
        s.commit()


def steps(client, h):
    return {x["key"]: x for x in client.get("/v1/setup/checklist", headers=h).json()["steps"]}


def test_site_step_creates_once_grants_access_and_refuses_timezone_changes(client):
    seed_tenant(client)
    h = ADMIN()
    assert steps(client, h)["sites"]["state"] == "todo"
    body = {"site_id": "syd_1", "name": "Sydney DC", "timezone": "Australia/Sydney"}
    assert client.post("/v1/setup/sites", json=body, headers=context_header(roles=["planner"], user_id="usr_pl", site_ids=["syd_1"])).status_code == 403
    assert client.post("/v1/setup/sites", json={**body, "timezone": "Mars/Base"}, headers=h).status_code == 400
    r = client.post("/v1/setup/sites", json=body, headers=h)
    assert r.status_code == 201 and r.json()["created"] is True
    again = client.post("/v1/setup/sites", json={**body, "name": "Sydney Hub"}, headers=h)          # a retry or refresh
    assert again.json()["created"] is False
    with client.session_local() as s:
        rows = s.scalars(select(Site)).all()
        assert [(x.site_id, x.name) for x in rows] == [("syd_1", "Sydney Hub")]
    assert client.post("/v1/setup/sites", json={**body, "timezone": "Australia/Perth"}, headers=h).status_code == 400
    assert steps(client, h)["sites"]["state"] == "done"


def test_state_is_remembered_optional_steps_can_be_skipped_and_done_comes_from_data(client):
    seed_tenant(client)
    h = ADMIN()
    assert client.get("/v1/setup/state", headers=h).json() == {"current_step": "sites", "attendance_choice": None, "skipped": []}
    r = client.put("/v1/setup/state", json={"current_step": "staff", "skipped": ["rates", "staff"]}, headers=h)
    assert r.json()["current_step"] == "staff" and r.json()["skipped"] == ["rates"]                 # only optional steps can be skipped
    assert client.get("/v1/setup/state", headers=context_header(roles=["operations_manager"], user_id="usr_ops", site_ids=["syd_1"])).json()["current_step"] == "staff"   # resumes for anyone in the org
    st = steps(client, h)
    assert st["rates"]["state"] == "skipped" and st["staff"]["state"] == "todo" and st["attendance"]["state"] == "todo"
    client.put("/v1/setup/state", json={"attendance_choice": "external"}, headers=h)
    assert steps(client, h)["attendance"]["state"] == "done" and "another system" in steps(client, h)["attendance"]["detail"]
    assert client.put("/v1/setup/state", json={"current_step": "bogus"}, headers=h).status_code == 422
    assert client.put("/v1/setup/state", json={"current_step": "roster"}, headers=context_header(roles=["analyst"], user_id="usr_an", site_ids=["syd_1"])).status_code == 403
    with client.session_local() as s:
        assert len(s.scalars(select(TenantSetup)).all()) == 1


def test_a_kiosk_device_completes_the_attendance_step_and_optional_steps_do_not_block_completion(client):
    from .conftest import enrol_kiosk
    seed_tenant(client)
    h = ADMIN()
    enrol_kiosk(client, site_ids=("syd_1",))
    assert steps(client, h)["attendance"]["state"] == "done" and "kiosk" in steps(client, h)["attendance"]["detail"]
    c = client.get("/v1/setup/checklist", headers=h).json()
    assert c["complete"] is False and c["next"] == "sites"
