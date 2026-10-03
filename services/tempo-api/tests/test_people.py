"""Badge numbers, active status and skills edited from the console."""
from __future__ import annotations

from sqlalchemy import select

from app.models.canonical import SkillCertification, Worker
from app.models.directory import Site, WorkerPerson
from app.models.identity import SecurityAuditEvent

from .conftest import context_header, enrol_kiosk
from app.core.kiosk import hash_pin
from app.models.attendance import WorkerCredential

SITE = "site_mel_01"
ADMIN = lambda: context_header(roles=["tenant_admin"], user_id="usr_adm")  # noqa: E731


def seed(client):
    enrol_kiosk(client)
    with client.session_local() as s:
        s.add(Site(tenant_id="ten_test", site_id=SITE, name="Mel", timezone="Australia/Melbourne"))
        s.flush()
        for wid, no in (("w1", "1001"), ("w2", "1002")):
            s.add(Worker(worker_id=wid, tenant_id="ten_test", employment_type="casual", home_site=SITE, status="active"))
            s.flush()
            s.add(WorkerPerson(worker_id=wid, tenant_id="ten_test", display_name=wid, employee_no=no))
            s.add(WorkerCredential(worker_id=wid, tenant_id="ten_test", pin_hash=hash_pin("1234")))
        s.commit()


def test_badge_numbers_are_unique_and_the_kiosk_follows_the_change(client):
    seed(client)
    kiosk = enrol_kiosk(client)
    assert client.patch("/v1/workers/w1", json={"badge_no": "2001"}, headers=context_header(roles=["planner"], user_id="usr_pl")).status_code == 403
    assert client.patch("/v1/workers/w1", json={"badge_no": "1002"}, headers=ADMIN()).status_code == 422          # w2 has it
    assert client.patch("/v1/workers/w1", json={"badge_no": "12ab"}, headers=ADMIN()).status_code == 422
    assert client.patch("/v1/workers/w1", json={"badge_no": "2001"}, headers=ADMIN()).json()["badge_no"] == "2001"
    old = client.post("/v1/attendance/whoami", json={"method": "pin", "worker_no": "1001", "pin": "1234"}, headers=kiosk)
    new = client.post("/v1/attendance/whoami", json={"method": "pin", "worker_no": "2001", "pin": "1234"}, headers=kiosk)
    assert old.status_code == 401 and new.status_code == 200


def test_inactive_people_cannot_clock_and_a_clocked_in_person_cannot_be_deactivated(client):
    seed(client)
    kiosk = enrol_kiosk(client)
    punch = lambda w, p: client.post(f"/v1/attendance/{p}", json={"method": "pin", "worker_id": w, "pin": "1234"}, headers=kiosk)  # noqa: E731
    assert punch("w1", "clock-in").status_code == 200
    blocked = client.patch("/v1/workers/w1", json={"status": "inactive"}, headers=ADMIN())
    assert blocked.status_code == 422 and "clocked in" in blocked.json()["detail"]
    punch("w1", "clock-out")
    assert client.patch("/v1/workers/w1", json={"status": "inactive"}, headers=ADMIN()).json()["status"] == "inactive"
    assert punch("w1", "clock-in").status_code == 401
    assert client.patch("/v1/workers/w1", json={"status": "active"}, headers=ADMIN()).json()["status"] == "active"
    assert punch("w1", "clock-in").status_code == 200
    with client.session_local() as s:
        acts = [e.action for e in s.scalars(select(SecurityAuditEvent).where(SecurityAuditEvent.action.like("worker.%")))]
        assert acts == ["worker.inactive", "worker.active"]


def test_skills_are_added_once_removed_and_scoped(client):
    seed(client)
    h = ADMIN()
    assert client.post("/v1/workers/w1/skills", json={"skill_code": "Forklift"}, headers=h).json()["skills"] == ["forklift"]
    assert client.post("/v1/workers/w1/skills", json={"skill_code": "forklift"}, headers=h).json()["skills"] == ["forklift"]      # no duplicate
    client.post("/v1/workers/w1/skills", json={"skill_code": "picker"}, headers=h)
    roster = {r["worker_id"]: r["skills"] for r in client.get(f"/v1/sites/{SITE}/clock-credentials", headers=h).json()}
    assert roster["w1"] == ["forklift", "picker"] and roster["w2"] == []
    assert client.post("/v1/workers/w1/skills", json={"skill_code": "x"}, headers=context_header(roles=["supervisor"], user_id="usr_sup")).status_code == 403
    assert client.delete("/v1/workers/w1/skills/Forklift", headers=h).json()["skills"] == ["picker"]
    assert client.delete("/v1/workers/w1/skills/forklift", headers=h).status_code == 404
    other = context_header(roles=["tenant_admin"], user_id="usr_o", site_ids=["site_elsewhere"])
    assert client.get("/v1/workers/w1/skills", headers=other).status_code == 404
    with client.session_local() as s:
        assert [x.skill_code for x in s.scalars(select(SkillCertification))] == ["picker"]
