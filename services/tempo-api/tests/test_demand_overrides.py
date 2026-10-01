"""Demand overrides: validated, reasoned, expiring, audited — and applied on top of (never into) the statistical forecast."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core import overrides as ov
from app.models.rosters import DemandOverride

from .conftest import context_header
from .test_roster_workflow import SITE, WEEK, _seed, manager, planner

NOW = datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)
OK = dict(activity=None, start_date=WEEK, end_date="2026-09-10", mode="multiply", value=1.25, reason="Promotion starts Tuesday; customer warned of a spike", expires_at=(datetime.now(timezone.utc) + timedelta(days=14)).isoformat())


def test_validation_rules():
    f = lambda **k: ov.validate(**{**dict(mode="multiply", value=1.2, start="2026-09-08", end="2026-09-10", reason="a proper reason", expires_at=NOW + timedelta(days=5), now=NOW), **k})  # noqa: E731
    assert f() is None
    assert "between" in f(value=5) and "between" in f(value=0.1)
    assert "units" in f(mode="set_units", value=-1)
    assert "mode" in f(mode="whatever")
    assert "before" in f(end="2026-09-01")
    assert "at most 14" in f(end="2026-10-30")
    assert "why" in f(reason="short")
    assert "future" in f(expires_at=NOW - timedelta(days=1))
    assert "at most 90" in f(expires_at=NOW + timedelta(days=200))


def _rows():
    return [{"activity": "pick", "bucket_start": f"2026-09-{d:02d}T14:00:00+00:00", "point": 100.0, "lower": 80.0, "upper": 120.0} for d in (8, 9, 11)]  # 00:00 Melbourne on 9, 10, 12


def test_multiply_set_units_and_scope():
    tz = ZoneInfo("Australia/Melbourne")
    o = DemandOverride(id="o1", tenant_id="t", site_id="s", activity="pick", start_date="2026-09-09", end_date="2026-09-10", mode="multiply", value=1.5, reason="x", expires_at=NOW, created_by="u")
    rows, used = ov.apply(_rows(), [o], tz)
    assert [r["point"] for r in rows] == [150.0, 150.0, 100.0] and used == ["o1"]            # only the two dates inside the range
    assert rows[0]["model_point"] == 100.0 and rows[0]["lower"] == 120.0 and rows[0]["upper"] == 180.0 and "override_ids" not in rows[2]
    s = DemandOverride(id="o2", tenant_id="t", site_id="s", activity=None, start_date="2026-09-12", end_date="2026-09-12", mode="set_units", value=40, reason="x", expires_at=NOW, created_by="u")
    rows, used = ov.apply(_rows(), [s], tz)
    assert rows[2]["point"] == 40.0 and rows[2]["model_point"] == 100.0 and rows[2]["lower"] <= 40.0 <= rows[2]["upper"] and used == ["o2"]
    other = DemandOverride(id="o3", tenant_id="t", site_id="s", activity="receive", start_date="2026-09-01", end_date="2026-09-30", mode="multiply", value=2, reason="x", expires_at=NOW, created_by="u")
    assert ov.apply(_rows(), [other], tz)[1] == []                                          # other activity: untouched


def test_override_lifecycle_audit_and_forecast(client):
    _seed(client)
    c = client
    base = c.get(f"/v1/sites/{SITE}/demand?start={WEEK}", headers=planner()).json()
    r = c.post(f"/v1/sites/{SITE}/demand/overrides", json=OK, headers=planner())
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    assert r.json()["status"] == "active" and r.json()["forecast_run_id"]
    d = c.get(f"/v1/sites/{SITE}/demand?start={WEEK}", headers=planner()).json()
    adj = [x for x in d["rows"] if x["adjusted"]]
    assert adj, "the forecast shown must carry the adjustment"
    for x in adj:
        assert x["forecast_units"] == round(x["model_units"] * 1.25) or abs(x["forecast_units"] - x["model_units"] * 1.25) <= 1
    assert d["overrides"][0]["id"] == oid and d["overrides"][0]["reason"].startswith("Promotion")
    # overlapping override for the same activity is refused rather than stacking
    assert c.post(f"/v1/sites/{SITE}/demand/overrides", json=OK, headers=planner()).status_code == 422
    # bad input is a 400-class, not a silent clamp
    assert c.post(f"/v1/sites/{SITE}/demand/overrides", json={**OK, "value": 9}, headers=planner()).status_code in (400, 422)
    assert c.post(f"/v1/sites/{SITE}/demand/overrides", json={**OK, "reason": "no"}, headers=planner()).status_code in (400, 422)
    # revoking needs a reason, keeps the row, and restores the model's numbers
    assert c.post(f"/v1/demand/overrides/{oid}/revoke", json={"reason": "x"}, headers=planner()).status_code == 422
    rv = c.post(f"/v1/demand/overrides/{oid}/revoke", json={"reason": "Promotion cancelled"}, headers=planner())
    assert rv.status_code == 200 and rv.json()["status"] == "revoked"
    assert c.post(f"/v1/demand/overrides/{oid}/revoke", json={"reason": "again please"}, headers=planner()).status_code == 422
    after = c.get(f"/v1/sites/{SITE}/demand?start={WEEK}", headers=planner()).json()
    assert not any(x["adjusted"] for x in after["rows"])
    assert [x["forecast_units"] for x in after["rows"]] == [x["model_units"] for x in after["rows"]]   # back to the model's own numbers
    assert [x["model_units"] for x in after["rows"]] == [x["model_units"] for x in d["rows"]]            # and the model number never moved
    assert after["overrides"][0]["status"] == "revoked"
    with client.session_local() as s:
        s.execute(text("SET LOCAL app.tenant_id = 'ten_test'"))
        assert s.execute(text("SELECT count(*) FROM demand_override")).scalar() == 1             # history is kept


def test_permissions_and_tenant_isolation(client):
    _seed(client)
    c = client
    assert c.post(f"/v1/sites/{SITE}/demand/overrides", json=OK, headers=context_header(roles=["analyst"], user_id="usr_an")).status_code == 403
    assert c.get(f"/v1/sites/{SITE}/demand/overrides", headers=context_header(roles=["analyst"], user_id="usr_an")).status_code == 200
    oid = c.post(f"/v1/sites/{SITE}/demand/overrides", json=OK, headers=planner()).json()["id"]
    assert c.post(f"/v1/demand/overrides/{oid}/revoke", json={"reason": "not mine to revoke"}, headers=context_header(roles=["analyst"], user_id="usr_an")).status_code == 403
    other = context_header(roles=["planner"], user_id="usr_o", tenant_id="ten_other")
    assert c.get(f"/v1/sites/{SITE}/demand/overrides", headers=other).status_code == 404
    assert c.post(f"/v1/demand/overrides/{oid}/revoke", json={"reason": "cross tenant attempt"}, headers=other).status_code == 404


def test_large_adjustments_need_a_second_person_before_they_touch_the_plan(client):
    _seed(client)
    c = client
    base = c.get(f"/v1/sites/{SITE}/demand?start={WEEK}", headers=planner()).json()
    big = {**OK, "value": 1.6}
    r = c.post(f"/v1/sites/{SITE}/demand/overrides", json=big, headers=planner())
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["needs_approval"] and r.json()["forecast_run_id"] is None
    oid = r.json()["id"]
    after = c.get(f"/v1/sites/{SITE}/demand?start={WEEK}", headers=planner()).json()
    assert not any(x["adjusted"] for x in after["rows"]) and [x["forecast_units"] for x in after["rows"]] == [x["forecast_units"] for x in base["rows"]]   # nothing moved
    assert c.post(f"/v1/sites/{SITE}/demand/overrides", json=big, headers=planner()).status_code == 422                       # a pending proposal blocks stacking too
    # the proposer cannot approve; a role without labour.approve cannot either
    assert c.post(f"/v1/demand/overrides/{oid}/approve", json={}, headers=planner()).status_code == 403
    # a different approver: rejection needs a reason, approval makes it live and re-runs the forecast
    assert c.post(f"/v1/demand/overrides/{oid}/reject", json={"note": "x"}, headers=manager()).status_code == 400
    ok = c.post(f"/v1/demand/overrides/{oid}/approve", json={"note": "agreed"}, headers=manager())
    assert ok.status_code == 200 and ok.json()["status"] == "active" and ok.json()["forecast_run_id"]
    d = c.get(f"/v1/sites/{SITE}/demand?start={WEEK}", headers=planner()).json()
    assert any(x["adjusted"] for x in d["rows"])
    assert c.post(f"/v1/demand/overrides/{oid}/approve", json={}, headers=manager()).status_code == 422                       # already decided
    # a proposer who is also an approver still cannot approve their own proposal
    both = context_header(roles=["planner", "operations_manager"], user_id="usr_both")
    mine = c.post(f"/v1/sites/{SITE}/demand/overrides", json={**big, "start_date": "2026-09-14", "end_date": "2026-09-15"}, headers=both).json()
    assert mine["status"] == "pending"
    assert c.post(f"/v1/demand/overrides/{mine['id']}/approve", json={}, headers=both).status_code == 403
    assert c.post(f"/v1/demand/overrides/{mine['id']}/approve", json={}, headers=manager()).status_code == 200
    # a rejected proposal never applies
    assert c.post(f"/v1/demand/overrides/{oid}/revoke", json={"reason": "reset for next check"}, headers=planner()).status_code == 200
    p2 = c.post(f"/v1/sites/{SITE}/demand/overrides", json={**big, "mode": "set_units", "value": 5000}, headers=planner()).json()
    assert p2["status"] == "pending"                                                                                       # fixed-units always needs a second person
    rj = c.post(f"/v1/demand/overrides/{p2['id']}/reject", json={"note": "not supported by the customer forecast"}, headers=manager()).json()
    assert rj["status"] == "rejected" and rj["decision_note"].startswith("not supported")
    rows = c.get(f"/v1/sites/{SITE}/demand?start={WEEK}", headers=planner()).json()["rows"]
    assert not any(x["adjusted"] for x in rows if x["date"] <= "2026-09-10")                                              # the rejected range stays on the model
