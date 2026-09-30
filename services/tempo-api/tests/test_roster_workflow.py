"""demand → roster → approval → publication: the roster version state machine, end to end over the API."""
from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.canonical import ShiftAssignment

from .conftest import context_header
from app.models.directory import Site

from .test_run_endpoint import _seed as _seed_canonical

SITE = "site_mel_01"
WEEK = "2026-09-08"


def _seed(client):
    _seed_canonical(client)
    with client.session_local() as s:
        s.add(Site(tenant_id="ten_test", site_id=SITE, name="Test DC", timezone="Australia/Melbourne", operating_mode="standalone"))
        s.commit()


def planner(**kw):
    return context_header(roles=["planner"], user_id="usr_planner", **kw)


def manager(**kw):
    return context_header(roles=["operations_manager"], user_id="usr_manager", **kw)


def gen(client):
    r = client.post(f"/v1/sites/{SITE}/rosters/generate", json={"week_start": WEEK}, headers=planner())
    assert r.status_code == 201, r.text
    return r.json()


def post(client, path, headers, body=None, idem=False):
    h = dict(headers)
    if idem:
        h["Idempotency-Key"] = str(uuid.uuid4())
    return client.post(path, json=body, headers=h) if body is not None else client.post(path, headers=h)


def test_generate_creates_an_editable_draft_owned_by_one_version(client):
    _seed(client)
    b = gen(client)
    v = b["version"]
    assert v["state"] == "draft" and v["version_no"] == 1 and v["source_run_id"]
    assert b["shifts"] and all(s["status"] == "proposed" for s in b["shifts"])
    with client.session_local() as s:
        rows = s.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_test")).all()
        assert all(r.source_ref == v["id"] for r in rows)
    # a second generation supersedes the first draft rather than piling up proposals
    b2 = gen(client)
    assert b2["version"]["version_no"] == 2
    with client.session_local() as s:
        assert len([r for r in s.scalars(select(ShiftAssignment)).all() if r.status == "proposed"]) == len(b2["shifts"])
        assert {r.status for r in s.scalars(select(ShiftAssignment).where(ShiftAssignment.source_ref == v["id"]))} <= {"superseded"}


def test_full_flow_publishes_once_and_reconciles(client):
    _seed(client)
    v = gen(client)["version"]["id"]
    assert post(client, f"/v1/rosters/{v}/validate", planner()).json()["can_submit"] is True
    sub = post(client, f"/v1/rosters/{v}/submit", planner())
    assert sub.status_code == 200 and sub.json()["state"] == "pending_approval"
    # (segregation of duties is asserted in test_submitter_cannot_approve_their_own_roster)
    pending = client.get("/v1/rosters/pending", headers=manager()).json()
    assert [p["id"] for p in pending] == [v] and pending[0]["impact"]["hard_conflicts"] == 0
    appr = post(client, f"/v1/rosters/{v}/approve", manager(), {"note": "looks right"})
    assert appr.status_code == 200 and appr.json()["state"] == "approved"
    # a planner cannot publish
    assert post(client, f"/v1/rosters/{v}/publish", planner(), idem=True).status_code == 403
    assert post(client, f"/v1/rosters/{v}/publish", manager()).status_code == 400  # Idempotency-Key required
    pub = post(client, f"/v1/rosters/{v}/publish", manager(), idem=True)
    assert pub.status_code == 200 and pub.json()["state"] == "reconciled", pub.text
    assert all(pub.json()["reconciliation"]["checks"].values())
    replay = post(client, f"/v1/rosters/{v}/publish", manager(), idem=True)
    assert replay.json()["idempotent_replay"] is True
    with client.session_local() as s:
        rows = s.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_test")).all()
        assert all(r.status == "committed" for r in rows)
        keys = [(r.worker_id, r.start_at) for r in rows]
        assert len(keys) == len(set(keys)), "no duplicate assignments"
    actions = [e["action"] for e in client.get(f"/v1/rosters/{v}/events", headers=manager()).json()]
    assert actions == ["generated", "submitted", "approved", "publishing", "published", "reconciled"]


def test_edit_after_submission_invalidates_approval(client):
    _seed(client)
    b = gen(client)
    v, first = b["version"]["id"], b["shifts"][0]
    post(client, f"/v1/rosters/{v}/submit", planner())
    post(client, f"/v1/rosters/{v}/approve", manager(), {})
    assert client.delete(f"/v1/rosters/{v}/shifts/{first['shift_id']}", headers=planner()).json()["version"]["state"] == "draft"
    assert post(client, f"/v1/rosters/{v}/publish", manager(), idem=True).status_code == 422  # no longer approved
    ev = [e["action"] for e in client.get(f"/v1/rosters/{v}/events", headers=manager()).json()]
    assert "approval_invalidated" in ev and "shift_removed" in ev


def test_hard_conflicts_block_submit_and_are_reported(client):
    _seed(client)
    b = gen(client)
    v, s0 = b["version"]["id"], b["shifts"][0]
    bad = client.post(f"/v1/rosters/{v}/shifts", headers=planner(), json={"worker_id": s0["worker_id"], "role": s0["role"], "zone": s0["zone"],
                                                                        "start_at": s0["start_at"], "end_at": s0["end_at"]})
    assert bad.status_code == 201
    kinds = {c["kind"] for c in bad.json()["conflicts"]}
    assert "overlap" in kinds and bad.json()["hard_conflicts"] > 0
    sub = post(client, f"/v1/rosters/{v}/submit", planner())
    assert sub.status_code == 422 and "hard conflict" in sub.json()["detail"]
    # fixing it (removing the duplicate) unblocks submission
    dup = next(s for s in bad.json()["shifts"] if s["worker_id"] == s0["worker_id"] and s["start_at"] == s0["start_at"] and s["shift_id"] != s0["shift_id"])
    client.delete(f"/v1/rosters/{v}/shifts/{dup['shift_id']}", headers=planner())
    assert post(client, f"/v1/rosters/{v}/submit", planner()).status_code == 200


def test_published_roster_is_copied_to_a_draft_and_replaces_the_old_one(client):
    _seed(client)
    v1 = gen(client)["version"]["id"]
    post(client, f"/v1/rosters/{v1}/submit", planner())
    post(client, f"/v1/rosters/{v1}/approve", manager(), {})
    post(client, f"/v1/rosters/{v1}/publish", manager(), idem=True)
    cp = client.post(f"/v1/sites/{SITE}/rosters/copy-published", json={"week_start": WEEK}, headers=planner())
    assert cp.status_code == 201 and cp.json()["version"]["source"] == "copy_of_published" and cp.json()["version"]["parent_version_id"] == v1
    v2, victim = cp.json()["version"]["id"], cp.json()["shifts"][0]
    client.delete(f"/v1/rosters/{v2}/shifts/{victim['shift_id']}", headers=planner())
    post(client, f"/v1/rosters/{v2}/submit", planner())
    post(client, f"/v1/rosters/{v2}/approve", manager(), {})
    assert post(client, f"/v1/rosters/{v2}/publish", manager(), idem=True).json()["state"] == "reconciled"
    with client.session_local() as s:
        rows = s.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == "ten_test")).all()
        live = [r for r in rows if r.status == "committed"]
        assert all(r.source_ref == v2 for r in live) and len(live) == len(cp.json()["shifts"]) - 1
        assert {r.status for r in rows if r.source_ref == v1} == {"superseded"}


def test_permissions_and_scope(client):
    _seed(client)
    v = gen(client)["version"]["id"]
    assert client.post(f"/v1/sites/{SITE}/rosters/generate", json={"week_start": WEEK}, headers=context_header(roles=["analyst"])).status_code == 403
    assert post(client, f"/v1/rosters/{v}/submit", context_header(roles=["supervisor"], user_id="usr_sup")).status_code == 403
    other = context_header(tenant_id="ten_other", site_ids=["site_x"], customer_ids=["c"], roles=["planner", "operations_manager"], user_id="usr_other")
    assert client.get(f"/v1/rosters/{v}", headers=other).status_code == 404
    assert client.delete(f"/v1/rosters/{v}/shifts/x", headers=other).status_code == 404
    assert client.get("/v1/rosters/pending", headers=other).json() == []
    other_site = context_header(site_ids=["site_zzz"], customer_ids=[], roles=["planner"], user_id="usr_zzz")
    assert client.get(f"/v1/rosters/{v}", headers=other_site).status_code in (400, 404)


def test_submitter_cannot_approve_their_own_roster(client):
    _seed(client)
    both = context_header(roles=["planner", "operations_manager"], user_id="usr_both")
    v = client.post(f"/v1/sites/{SITE}/rosters/generate", json={"week_start": WEEK}, headers=both).json()["version"]["id"]
    assert post(client, f"/v1/rosters/{v}/submit", both).status_code == 200
    r = post(client, f"/v1/rosters/{v}/approve", both, {"note": "me"})
    assert r.status_code == 403 and "segregation" in r.json()["detail"]
    assert post(client, f"/v1/rosters/{v}/approve", manager(), {"note": "independent"}).status_code == 200
