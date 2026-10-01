"""Operations read models + exception lifecycle, against the real bootstrap_ensemble_demo dataset."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app import db as db_module
from app.core import auth
from app.demo import ensemble
from app.main import app
from app.models.identity import TempoUser
from sqlalchemy import select

MEL, SYD = "mel_dc_01", "syd_dc_02"


@pytest.fixture(scope="module")
def demo(owner_engine, app_engine, tmp_path_factory):
    """Seed once per module (7s), then reuse: read-only tests share it; lifecycle tests reseed with reset."""
    from sqlalchemy import text

    mp = pytest.MonkeyPatch()
    with owner_engine.begin() as c:
        tables = [r[0] for r in c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version'"))]
        c.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " CASCADE"))
    sl = sessionmaker(bind=app_engine, autoflush=False, autocommit=False)
    import app.dependencies as dep
    mp.setattr(db_module, "engine", app_engine)
    mp.setattr(db_module, "SessionLocal", sl)
    mp.setattr(dep, "SessionLocal", sl)
    result = ensemble.bootstrap(reset_first=False, secrets_dir=str(tmp_path_factory.mktemp("demo-secrets")))
    tokens = {}
    with sl() as s:
        db_module.begin_auth_lookup(s)
        for u in s.scalars(select(TempoUser).where(TempoUser.email.like("%@demo.tempo.invalid"))):
            tokens[u.external_subject.split("|")[1]] = auth.create_session(s, u, mfa=True, auth_method="test").access_token
        s.commit()
    client = TestClient(app)
    yield {"client": client, "tokens": tokens, "result": result, "sl": sl}
    mp.undo()


def H(demo, persona):
    return {"Authorization": f"Bearer {demo['tokens'][persona]}"}


def test_seed_is_labelled_synthetic_and_idempotent(demo):
    assert demo["result"]["manifest"]["synthetic"] is True
    again = ensemble.bootstrap(reset_first=False)
    assert again["result"] == "already_seeded"
    sites = demo["client"].get("/v1/sites", headers=H(demo, "ops_manager")).json()
    assert {s["site_id"] for s in sites} == {MEL, SYD} and all(s["is_synthetic"] for s in sites)
    assert all("synthetic" in s["name"].lower() for s in sites)


def test_seed_refuses_production(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "env", "production")
    with pytest.raises(RuntimeError, match="production"):
        ensemble.bootstrap()


def test_overview_kpis_carry_definitions_and_real_numbers(demo):
    ov = demo["client"].get(f"/v1/sites/{MEL}/overview", headers=H(demo, "ops_manager")).json()
    keys = {k["key"]: k for k in ov["kpis"]}
    assert set(keys) >= {"scheduled_workers", "clocked_in", "coverage", "work_units", "labour_cost", "open_exceptions"}
    assert all(k["definition"] for k in ov["kpis"])
    assert keys["scheduled_workers"]["value"] > 0 and keys["coverage"]["value"] is not None
    assert ov["site"]["timezone"] == "Australia/Melbourne" and len(ov["hourly"]) in (23, 24, 25)
    assert ov["forecast"]["method"] and "Holt" in ov["forecast"]["method"]
    assert ov["metric_version"].startswith("tempo-metrics")
    cells = ov["heatmap"]["cells"]
    assert cells and {c["status"] for c in cells} <= {"covered", "risk", "shortage", "no_demand"} and all(c["label"] for c in cells)


def test_hourly_capacity_reconciles_to_published_shifts(demo):
    ov = demo["client"].get(f"/v1/sites/{MEL}/overview", headers=H(demo, "ops_manager")).json()
    ro = demo["client"].get(f"/v1/sites/{MEL}/roster", headers=H(demo, "planner")).json()
    from datetime import datetime
    day_hours = sum(h["staffed_hours"] for h in ov["hourly"])
    d0 = datetime.fromisoformat(ov["hourly"][0]["hour_start"].replace("Z", "+00:00")).timestamp()
    d1 = d0 + len(ov["hourly"]) * 3600
    manual = 0.0
    for s in ro["shifts"]:
        a = datetime.fromisoformat(s["start_at"].replace("Z", "+00:00")).timestamp()
        b = datetime.fromisoformat(s["end_at"].replace("Z", "+00:00")).timestamp()
        manual += max(0.0, min(b, d1) - max(a, d0)) / 3600
    assert abs(day_hours - manual) < 0.5  # board and chart agree to within rounding


def test_missing_data_is_not_zero(demo):
    ov = demo["client"].get(f"/v1/sites/{SYD}/overview", headers=H(demo, "ops_manager")).json()
    keys = {k["key"]: k for k in ov["kpis"]}
    assert keys["coverage"]["value"] is None and keys["coverage"]["display"] == "No verified data"
    assert keys["clocked_in"]["value"] is None and keys["clocked_in"]["reason"]


def test_stale_connector_is_never_shown_as_all_present(demo):
    live = demo["client"].get(f"/v1/sites/{SYD}/attendance/live", headers=H(demo, "ops_manager")).json()
    assert live["attendance_verified"] is False and live["stale_message"]
    assert live["counts"]["present"] is None and live["counts"]["absent"] is None and live["counts"]["unrostered"] is None
    assert not any(r["state"] == "absent" for r in live["rows"])
    kinds = {e["kind"] for e in live["exceptions"]}
    assert "connector_stale" in kinds and "no_show" not in kinds  # absence suppressed while the source is stale
    src = next(s for s in live["data_sources"] if s["key"] == "attendance")
    assert src["mode"] == "stale" and "SIMULATED" in src["label"]


def test_melbourne_live_attendance_counts_and_definitions(demo):
    live = demo["client"].get(f"/v1/sites/{MEL}/attendance/live", headers=H(demo, "supervisor")).json()
    assert live["attendance_verified"] is True
    assert set(live["definitions"]) == {"expected", "present", "late", "absent", "unrostered"}
    assert live["counts"]["unrostered"] >= 1  # seeded unrostered punch
    kinds = {e["kind"] for e in live["exceptions"]}
    assert "unrostered" in kinds
    for e in live["exceptions"]:
        assert e["detection_lag_seconds"] >= 0 and e["source_occurred_at"] and e["detected_at"]


def test_names_and_rates_are_permission_gated(demo):
    ex = demo["client"].get(f"/v1/sites/{MEL}/overview", headers=H(demo, "analyst")).json()
    assert "labour_cost" not in {k["key"] for k in ex["kpis"]}  # analyst has no labour.rates.read
    assert all("(synthetic)" not in (a["worker_label"] or "") and (a["worker_id"] is None) for a in ex["attention"])
    ro = demo["client"].get(f"/v1/sites/{MEL}/roster", headers=H(demo, "analyst")).json()
    assert all(w["label"].startswith("Worker …") for w in ro["workers"]) and "cost" not in ro["totals"]["published"]
    mgr = demo["client"].get(f"/v1/sites/{MEL}/roster", headers=H(demo, "ops_manager")).json()
    assert any("(synthetic)" in w["label"] for w in mgr["workers"]) and "cost" in mgr["totals"]["published"]


def test_site_outside_grants_is_a_404(demo):
    c = demo["client"]
    assert c.get(f"/v1/sites/{SYD}/overview", headers=H(demo, "planner")).status_code == 404  # planner has Melbourne only
    assert c.get(f"/v1/sites/{SYD}/roster", headers=H(demo, "supervisor")).status_code == 404
    assert c.get("/v1/sites/nope/overview", headers=H(demo, "ops_manager")).status_code == 404


def test_roster_is_published_once_and_has_no_hard_conflicts_or_explains_them(demo):
    ro = demo["client"].get(f"/v1/sites/{MEL}/roster", headers=H(demo, "planner")).json()
    ids = [s["shift_id"] for s in ro["shifts"]]
    assert len(ids) == len(set(ids)) and ro["view"] == "published"
    assert all(s["status"] == "committed" for s in ro["shifts"])
    assert ro["totals"]["published"]["shifts"] == len(ro["shifts"])
    assert ro["totals"]["draft"]["shifts"] == 0
    for c in ro["conflicts"]:
        assert c["kind"] in {"overlap", "rest", "availability", "certification", "site_eligibility", "max_hours"} and c["detail"]
    assert ro["publication"]["can_publish"] == (ro["hard_conflicts"] == 0)


def test_exception_detection_is_idempotent_and_lifecycle_is_audited(demo):
    c, sup = demo["client"], H(demo, "supervisor")
    first = c.post(f"/v1/sites/{MEL}/exceptions/detect", headers=sup).json()
    second = c.post(f"/v1/sites/{MEL}/exceptions/detect", headers=sup).json()
    assert second["new_cases"] == {}, "re-running detection must not duplicate cases"
    live = c.get(f"/v1/sites/{MEL}/attendance/live", headers=sup).json()
    case = next(e for e in live["exceptions"] if e["state"] == "detected")
    assert c.post(f"/v1/exceptions/{case['id']}/acknowledge", headers=sup).json()["state"] == "triaged"
    assert c.post(f"/v1/exceptions/{case['id']}/assign", headers=sup).json()["state"] == "assigned"
    assert c.post(f"/v1/exceptions/{case['id']}/resolve", headers=sup, json={"reason": "x"}).status_code == 422  # reason too short
    done = c.post(f"/v1/exceptions/{case['id']}/resolve", headers=sup, json={"reason": "Spoke to worker; bus delay"}).json()
    assert done["state"] == "resolved"
    assert c.post(f"/v1/exceptions/{case['id']}/resolve", headers=sup, json={"reason": "again"}).status_code == 400  # already closed


def test_exception_actions_need_the_manage_permission_and_site_scope(demo):
    c = demo["client"]
    live = c.get(f"/v1/sites/{MEL}/attendance/live", headers=H(demo, "supervisor")).json()
    case = next(e for e in live["exceptions"] if e["state"] in ("detected", "triaged", "assigned"))
    assert c.post(f"/v1/exceptions/{case['id']}/acknowledge", headers=H(demo, "analyst")).status_code == 403
    assert c.post(f"/v1/exceptions/{case['id']}/dismiss", headers=H(demo, "executive"), json={"reason": "not mine"}).status_code == 403
    assert c.post("/v1/exceptions/does-not-exist/acknowledge", headers=H(demo, "supervisor")).status_code == 404


def test_csv_export_is_gated_audited_and_formula_safe(demo):
    from app.core.exports import safe_cell, to_csv
    c = demo["client"]
    assert safe_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)" and safe_cell("-1+2") == "'-1+2" and safe_cell(-3) == "-3" and safe_cell(None) == ""
    assert "'=x" in to_csv(["a"], [["=x"]], ["p"])
    for kind in ("variance", "timesheets", "demand"):
        r = c.get(f"/v1/sites/{MEL}/exports/{kind}.csv", headers=H(demo, "ops_manager"))
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv") and "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
        assert r.text.startswith("# Tempo ")
    # screens-only roles cannot take a copy; unknown kind and out-of-scope site are not found
    assert c.get(f"/v1/sites/{MEL}/exports/variance.csv", headers=H(demo, "analyst")).status_code == 403
    assert c.get(f"/v1/sites/{MEL}/exports/payroll.csv", headers=H(demo, "ops_manager")).status_code == 404
    assert c.get("/v1/sites/nope/exports/variance.csv", headers=H(demo, "ops_manager")).status_code == 404
    # rates only appear for callers who may see them
    hdr = lambda t: next(l for l in t.splitlines() if not l.startswith("#"))  # noqa: E731
    assert "planned_cost" in hdr(c.get(f"/v1/sites/{MEL}/exports/variance.csv", headers=H(demo, "ops_manager")).text)
    # the export is in the audit trail with its row count
    from sqlalchemy import text
    with demo["sl"]() as s:
        db_module.begin_auth_lookup(s)
        assert s.execute(text("SELECT count(*) FROM security_audit_event WHERE action LIKE 'export.%' AND reason_code LIKE 'rows=%'")).scalar() >= 3


def _week_in(weeks: int) -> str:
    from datetime import date, timedelta
    d = date.today() + timedelta(weeks=weeks)
    return (d - timedelta(days=d.weekday())).isoformat()


def test_notifications_are_personal_scoped_and_workflow_driven(demo):
    c = demo["client"]
    mine = lambda who, **q: c.get("/v1/notifications", headers=H(demo, who), params=q).json()  # noqa: E731
    # urgent exceptions reach the people who can act on them — and not people who cannot
    sup = mine("supervisor")
    assert sup["unread"] > 0 and any(i["kind"].startswith("exception.") and i["severity"] == "urgent" for i in sup["items"])
    assert not any(i["kind"].startswith("exception.") for i in mine("analyst")["items"])
    # a roster workflow: submit → approvers are told (not the submitter); approve → the submitter is told
    week = _week_in(11)
    b = c.post(f"/v1/sites/{MEL}/rosters/generate", json={"week_start": week}, headers=H(demo, "planner"))
    assert b.status_code == 201, b.text
    vid = b.json()["version"]["id"]
    before = mine("ops_manager")["unread"]
    assert c.post(f"/v1/rosters/{vid}/submit", headers=H(demo, "planner")).status_code == 200
    ops = mine("ops_manager")
    sub = next(i for i in ops["items"] if i["kind"] == "roster.submitted" and week in i["title"])
    assert ops["unread"] == before + 1 and sub["link"] == "/approvals" and sub["severity"] == "action"
    assert not any(week in i["title"] for i in mine("planner")["items"])                      # the actor is never notified of their own action
    assert c.post(f"/v1/rosters/{vid}/approve", json={"note": "ok"}, headers=H(demo, "ops_manager")).status_code == 200
    ap = next(i for i in mine("planner")["items"] if i["kind"] == "roster.approved" and week in i["title"])
    assert ap["link"].startswith("/roster?start=" + week)
    # read state is per user; nobody can touch another user's notice
    assert c.post(f"/v1/notifications/{ap['id']}/read", headers=H(demo, "ops_manager")).status_code == 404
    assert c.post(f"/v1/notifications/{ap['id']}/read", headers=H(demo, "planner")).json()["read_at"]
    assert all(i["id"] != ap["id"] for i in mine("planner", unread="true")["items"])
    n = c.post("/v1/notifications/read-all", headers=H(demo, "ops_manager")).json()["marked"]
    assert n >= 1 and mine("ops_manager")["unread"] == 0
    assert mine("supervisor")["unread"] == sup["unread"]                                      # someone else's read-all did not touch them
    assert c.get("/v1/notifications").status_code == 401


SYD = "syd_dc_02"


def _publish_week(demo, site, week):
    """Standalone: solve a draft. Overlay demo site: it has a (simulated) live roster but no demand history, so adjust a copy of what is live."""
    c = demo["client"]
    author = "planner" if site == MEL else "tenant_admin"      # the Melbourne-only planner has no Sydney grant
    if site == MEL:
        g = c.post(f"/v1/sites/{site}/rosters/generate", json={"week_start": week}, headers=H(demo, author))
    else:
        g = c.post(f"/v1/sites/{site}/rosters/copy-published", json={"week_start": week}, headers=H(demo, author))
    assert g.status_code == 201, g.text
    vid = g.json()["version"]["id"]
    assert c.post(f"/v1/rosters/{vid}/submit", headers=H(demo, author)).status_code == 200
    assert c.post(f"/v1/rosters/{vid}/approve", json={"note": "ok"}, headers=H(demo, "ops_manager")).status_code == 200
    r = c.post(f"/v1/rosters/{vid}/publish", headers={**H(demo, "ops_manager"), "Idempotency-Key": f"pub-{vid}"})
    assert r.status_code == 200 and r.json()["state"] == "reconciled", r.text
    return vid


def test_overlay_publish_creates_a_handoff_that_is_never_claimed_vendor_confirmed_without_a_connector(demo, monkeypatch, owner_engine):
    from sqlalchemy import text
    from app.maestro import roster_handoff as rh
    c, week = demo["client"], _week_in(0)
    mel = _publish_week(demo, MEL, _week_in(5))
    assert c.get(f"/v1/sites/{MEL}/handoffs", headers=H(demo, "ops_manager"), params={"version_id": mel}).json() == []        # standalone: nothing to hand off
    vid = _publish_week(demo, SYD, week)
    hs = c.get(f"/v1/sites/{SYD}/handoffs", headers=H(demo, "ops_manager"), params={"version_id": vid}).json()
    assert len(hs) == 1 and hs[0]["state"] == "pending" and hs[0]["shifts"] > 0
    hid = hs[0]["id"]
    # the file: approvers only, audited, hashed; taking it moves pending → exported
    assert c.get(f"/v1/handoffs/{hid}/file.csv", headers=H(demo, "tenant_admin")).status_code == 403    # admin plans but does not approve
    assert c.post(f"/v1/handoffs/{hid}/confirm", json={"reference": "IMP-1"}, headers=H(demo, "ops_manager")).status_code == 422   # nothing to attest yet
    f = c.get(f"/v1/handoffs/{hid}/file.csv", headers=H(demo, "ops_manager"))
    assert f.status_code == 200 and "worker_ref" in f.text and f.headers["cache-control"] == "no-store"
    h = c.get(f"/v1/sites/{SYD}/handoffs", headers=H(demo, "ops_manager")).json()[0]
    assert h["state"] == "exported" and len(h["file_sha256"]) == 64
    # an operator attestation is labelled as such — it is not vendor confirmation
    assert c.post(f"/v1/handoffs/{hid}/confirm", json={"reference": "x"}, headers=H(demo, "ops_manager")).status_code == 422       # reference too short
    ok = c.post(f"/v1/handoffs/{hid}/confirm", json={"reference": "IMP-1001", "note": "loaded by hand"}, headers=H(demo, "ops_manager")).json()
    assert ok["state"] == "confirmed_by_operator" and ok["confirmation_kind"] == "operator_attestation"

    # vendor submit: needs the idempotency key, the tenant switch, and a person other than the publisher
    vid2 = _publish_week(demo, SYD, week)
    hid2 = c.get(f"/v1/sites/{SYD}/handoffs", headers=H(demo, "ops_manager"), params={"version_id": vid2}).json()[0]["id"]
    ops = H(demo, "ops_manager")
    assert c.post(f"/v1/handoffs/{hid2}/submit", headers=ops).status_code == 400                                                    # no Idempotency-Key
    assert c.post(f"/v1/handoffs/{hid2}/submit", headers={**ops, "Idempotency-Key": "k1"}).status_code == 422                      # kill switch off
    with owner_engine.begin() as conn:
        conn.execute(text("UPDATE tenant SET writeback_enabled = true WHERE tenant_id = 'ensemble_solutions'"))
        conn.execute(text("UPDATE roster_version SET published_by = 'someone_else' WHERE id = :v"), {"v": vid2})
    try:
        r = c.post(f"/v1/handoffs/{hid2}/submit", headers={**ops, "Idempotency-Key": "k1"}).json()
        assert r["state"] == "unconfirmed" and r["attempts"] == 1 and "no vendor roster connector" in r["vendor_detail"]       # honest default: unknown stays open
        assert r["confirmation_kind"] is None

        class Fake:
            def __init__(self, status): self.status, self.calls = status, []
            def submit_roster(self, site_id, payload_hash, shifts, key):
                self.calls.append(key)
                return rh.HandoffOutcome(self.status, "fake vendor")
        fake = Fake("confirmed")
        monkeypatch.setattr(rh, "vendor_roster_client", fake)
        r = c.post(f"/v1/handoffs/{hid2}/submit", headers={**ops, "Idempotency-Key": "k2"}).json()
        assert r["state"] == "vendor_confirmed" and r["confirmation_kind"] == "vendor" and len(fake.calls) == 1
        again = c.post(f"/v1/handoffs/{hid2}/submit", headers={**ops, "Idempotency-Key": "k3"}).json()
        assert again["idempotent_replay"] is True and len(fake.calls) == 1                                                          # never sent twice
        # same publisher is refused (segregation of duties)
        vid3 = _publish_week(demo, SYD, week)
        hid3 = c.get(f"/v1/sites/{SYD}/handoffs", headers=ops, params={"version_id": vid3}).json()[0]["id"]
        assert c.post(f"/v1/handoffs/{hid3}/submit", headers={**ops, "Idempotency-Key": "k4"}).status_code == 403
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE roster_version SET published_by = 'someone_else' WHERE id = :v"), {"v": vid3})
        monkeypatch.setattr(rh, "vendor_roster_client", Fake("rejected"))
        assert c.post(f"/v1/handoffs/{hid3}/submit", headers={**ops, "Idempotency-Key": "k5"}).json()["state"] == "rejected"
    finally:
        with owner_engine.begin() as conn:
            conn.execute(text("UPDATE tenant SET writeback_enabled = false WHERE tenant_id = 'ensemble_solutions'"))
    # a newer publish for the same week retires an open handoff
    vid4 = _publish_week(demo, SYD, week)   # same week as vid2 (vendor_confirmed, closed) and vid3's week differs; vid2 stays confirmed
    st = {h["version_id"]: h["state"] for h in c.get(f"/v1/sites/{SYD}/handoffs", headers=ops).json()}
    assert st[vid2] == "vendor_confirmed" and st[vid4] == "pending"


def test_tenant_audit_log_is_admin_only_scoped_filterable_and_self_recording(demo):
    c = demo["client"]
    for _ in range(7):                                                                           # make sure there is something to page through
        assert c.get(f"/v1/sites/{MEL}/exports/demand.csv", headers=H(demo, "ops_manager")).status_code == 200
    assert c.get("/v1/admin/audit", headers=H(demo, "ops_manager")).status_code == 403        # approving rosters is not administering users
    assert c.get("/v1/admin/audit", headers=H(demo, "analyst")).status_code == 403
    r = c.get("/v1/admin/audit", headers=H(demo, "tenant_admin"), params={"limit": 5})
    assert r.status_code == 200
    d = r.json()
    assert len(d["items"]) == 5 and d["next_before"] and "roster" not in d["items"][0].get("secret", "")
    assert all(set(i) >= {"at", "actor_id", "action", "decision", "correlation_id"} for i in d["items"])
    assert d["items"] == sorted(d["items"], key=lambda i: i["at"], reverse=True)
    page2 = c.get("/v1/admin/audit", headers=H(demo, "tenant_admin"), params={"limit": 5, "before": d["next_before"]}).json()
    assert {i["event_id"] for i in page2["items"]}.isdisjoint({i["event_id"] for i in d["items"]})
    only = c.get("/v1/admin/audit", headers=H(demo, "tenant_admin"), params={"action": "export."}).json()
    assert only["items"] and all(i["action"].startswith("export.") for i in only["items"])
    assert any(a.startswith("export.") for a in only["actions"])
    seen = c.get("/v1/admin/audit", headers=H(demo, "tenant_admin"), params={"action": "audit.view"}).json()
    assert seen["items"], "viewing the audit log is itself audited"
    named = [i for i in d["items"] + page2["items"] if i["actor_type"] == "user" and i["actor_name"]]
    assert named, "user actors are shown by name when they belong to this tenant"


def test_demo_reset_refuses_databases_that_are_not_throwaway(demo, monkeypatch):
    from types import SimpleNamespace
    from app.demo import ensemble as e
    fake = lambda name: SimpleNamespace(get_bind=lambda: SimpleNamespace(url=SimpleNamespace(database=name)))  # noqa: E731
    e._guard_reset(fake("tempo_e2e"))
    e._guard_reset(fake("tempo_test"))
    monkeypatch.delenv("TEMPO_DEMO_RESET_DB", raising=False)
    with pytest.raises(RuntimeError, match="refusing to reset"):
        e._guard_reset(fake("tempo"))
    monkeypatch.setenv("TEMPO_DEMO_RESET_DB", "tempo")           # only an explicit, named opt-in unlocks it
    e._guard_reset(fake("tempo"))
    with pytest.raises(RuntimeError):
        e._guard_reset(fake("tempo_other"))
