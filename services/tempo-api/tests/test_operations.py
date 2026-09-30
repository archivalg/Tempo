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
