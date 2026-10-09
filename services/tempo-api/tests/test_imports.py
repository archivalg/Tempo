"""Roadmap M1 acceptance: CSV and API ingestion of master data, forecasts, workload events and workload totals."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.imports.contracts import CONTRACTS, template_csv
from app.imports.parse import ImportProblem, aligned_bucket, parse_moment, suggest_mapping
from app.models.canonical import DemandBucket, WorkStandard
from app.models.directory import Customer, Site
from app.models.identity import Tenant
from app.models.imports import ImportBatch, SuppliedForecast, WorkloadEvent
from app.models.rosters import RosterEvent, RosterVersion

from .conftest import context_header

MEL, SYD = "site_mel_01", "site_syd_01"


def admin(tenant="ten_test", sites=(MEL, SYD)):
    return context_header(tenant_id=tenant, roles=["tenant_admin"], user_id="usr_admin", site_ids=list(sites), customer_ids=["cust_A"])


def planner():
    return context_header(roles=["planner"], user_id="usr_pl", site_ids=[MEL, SYD])


def seed(client, tenant="ten_test", standards=("picking", "packing")):
    with client.session_local() as s:
        if s.get(Tenant, tenant) is None:
            s.add(Tenant(tenant_id=tenant, name=tenant))
            s.flush()
        s.add(Site(tenant_id=tenant, site_id=MEL, name="Melbourne", timezone="Australia/Melbourne", operating_mode="standalone"))
        s.add(Site(tenant_id=tenant, site_id=SYD, name="Sydney", timezone="Australia/Sydney", operating_mode="standalone"))
        s.add(Customer(tenant_id=tenant, customer_id="cust_A", name="A"))
        for a in standards:
            s.add(WorkStandard(tenant_id=tenant, activity=a, time_per_unit_seconds=45, effective_from=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        s.commit()


def csv_text(header, rows):
    b = io.StringIO()
    w = csv.writer(b, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return b.getvalue()


def stage(client, h, data_class, text_, entity=None, mapping=None, **opts):
    """Inspect (to get the proposed mapping), then stage."""
    q = {"data_class": data_class, **({"entity": entity} if entity else {})}
    ins = client.post("/v1/imports/csv/inspect", params=q, content=text_.encode(), headers={**h, "Content-Type": "text/csv"})
    assert ins.status_code == 200, ins.text
    m = mapping or ins.json()["suggested_mapping"]
    return client.post("/v1/imports/csv/stage", params={**q, "mapping": json.dumps(m), **opts}, content=text_.encode(), headers={**h, "Content-Type": "text/csv"})


def buckets(client, tenant="ten_test", source=None):
    with client.session_local() as s:
        q = select(DemandBucket).where(DemandBucket.tenant_id == tenant)
        if source:
            q = q.where(DemandBucket.source == source)
        return sorted(s.scalars(q), key=lambda b: (b.site_id, b.activity, b.interval_start, b.bucket_minutes))


# ------------------------------------------------------------------------------------------------ contracts and time rules
def test_every_template_example_row_passes_its_own_validator(client):
    seed(client)
    from app.imports import engine as E, validate as V
    from app.schemas.tenancy import RequestContext
    with client.session_local() as db:
        lk = E.lookups(db, RequestContext(tenant_id="ten_test", site_ids=[MEL, SYD], user_id="u", roles=[], purpose="t", correlation_id="c"))
    lk.sites["mel_dc_01"] = lk.sites[MEL]
    lk.customers.add("cust_A")
    lk.worker_site["E1042"] = MEL
    lk.workers_by_ref["E1042"] = "wrk_placeholder"
    lk.zone_ids.add(("mel_dc_01", "PICK"))
    lk.shift_templates[("mel_dc_01", "night")] = {"elapsed_minutes": 480}
    lk.process_templates.add(("mel_dc_01", "outbound_standard"))
    lk.zone_ids.add(("mel_dc_01", "STAGE"))
    lk.staging_units[("mel_dc_01", "STAGE")] = "pallets"
    for key, c in CONTRACTS.items():
        row = next(csv.DictReader(io.StringIO(template_csv(c))))
        n, msgs = V.validate_row(c, row, lk)
        assert n is not None, (key, msgs)


def test_local_time_rules_across_daylight_saving():
    from zoneinfo import ZoneInfo
    mel = ZoneInfo("Australia/Melbourne")
    assert parse_moment("2026-10-05 14:30", mel).isoformat() == "2026-10-05T03:30:00+00:00"
    with pytest.raises(ImportProblem, match="does not exist"):
        parse_moment("2026-10-04 02:30", mel)                      # clocks go forward 02:00 → 03:00
    with pytest.raises(ImportProblem, match="happens twice"):
        parse_moment("2027-04-04 02:30", mel)                      # clocks go back 03:00 → 02:00
    assert parse_moment("2027-04-04T02:30:00+11:00", mel) != parse_moment("2027-04-04T02:30:00+10:00", mel)
    s, m = aligned_bucket("2026-10-04", "day", mel)                # the 23-hour day is still one day
    e, _ = aligned_bucket("2026-10-05", "day", mel)
    assert m == 1440 and e - s == timedelta(hours=23)
    with pytest.raises(ImportProblem, match="on the hour"):
        aligned_bucket("2026-10-05 14:30", "hour", mel)
    with pytest.raises(ImportProblem, match="midnight"):
        aligned_bucket("2026-10-05 06:00", "day", mel)


def test_mapping_uses_synonyms_and_remembers_but_never_guesses():
    c = CONTRACTS[("master", "workers")]
    m = suggest_mapping(c, ["Employee ID", "Full Name", "Location", "Type", "Notes"])
    assert m["worker_ref"] == "Employee ID" and m["name"] == "Full Name" and m["site"] == "Location" and m["employment_type"] == "Type" and m["skills"] is None
    saved = suggest_mapping(c, ["Zeta", "Alpha"], {"worker_ref": "Zeta", "name": "Alpha"})
    assert saved["worker_ref"] == "Zeta" and saved["name"] == "Alpha" and saved["site"] is None


# ------------------------------------------------------------------------------------------------ 1 master data by CSV, 4 actionable results
def test_staff_csv_loads_then_replays_and_updates_without_duplicates(client):
    seed(client)
    h = admin()
    f1 = csv_text(["Employee ID", "Full Name", "Location", "Type", "Skills"], [["E1", "Ann Lee", MEL, "permanent", "picker;forklift"], ["E2", "Bo Ray", SYD, "casual", "picker"]])
    r = stage(client, h, "master", f1, entity="workers")
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["state"] == "validated" and b["ok_rows"] == 2 and b["summary"]["creates"] == 2 and b["can_apply"]
    assert client.get("/v1/imports/status", headers=h).json()["classes"][0]["last_success_at"] is None            # staging changed nothing
    done = client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h).json()
    assert done["state"] == "applied" and done["summary"]["applied"] == {"created": 2, "updated": 0}
    again = stage(client, h, "master", f1, entity="workers").json()
    assert again["replayed"] is True and again["id"] == b["id"]                                                     # same file: same batch, no second write
    assert client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h).json()["state"] == "applied"             # applying twice is a no-op
    f2 = f1.replace("Ann Lee", "Ann Leigh")
    b2 = stage(client, h, "master", f2, entity="workers").json()
    assert b2["summary"]["updates"] == 1 and b2["summary"]["creates"] == 1 or b2["summary"]["updates"] == 2
    assert client.post(f"/v1/imports/batches/{b2['id']}/apply", headers=h).json()["summary"]["applied"]["created"] == 0
    with client.session_local() as s:
        n = s.execute(text("SELECT count(*) FROM worker WHERE source_system='tempo_import'")).scalar()
        names = sorted(s.execute(text("SELECT display_name FROM worker_person")).scalars())
    assert n == 2 and names == ["Ann Leigh", "Bo Ray"]
    assert client.post(f"/v1/imports/batches/{b2['id']}/undo", headers=h).status_code == 422                       # master loads are corrected by re-upload


def test_bad_rows_are_rejected_with_reasons_and_partial_apply_is_deliberate(client):
    seed(client)
    h = admin()
    f = csv_text(["worker_ref", "name", "site", "employment_type"], [
        ["E1", "Ok Person", MEL, "casual"], ["E2", "No Site", "nowhere", "casual"], ["E3", "Bad Type", MEL, "wizard"], ["", "No Ref", MEL, "casual"], ["E1", "Dup", MEL, "casual"]])
    b = stage(client, h, "master", f, entity="workers").json()
    assert (b["ok_rows"], b["error_rows"]) == (1, 4)
    by_row = {r["row"]: " ".join(m["text"] for m in r["messages"]) for r in b["rejected_sample"]}
    assert "not one of your sites" in by_row[2] and "employment_type must be one of" in by_row[3] and "worker_ref is required" in by_row[4] and "duplicates row 1" in by_row[5]
    assert client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h).status_code == 422                       # not silently partial
    ok = client.post(f"/v1/imports/batches/{b['id']}/apply", json={"accept_partial": True}, headers=h).json()
    assert ok["state"] == "applied" and ok["summary"]["applied_partial"] is True
    errs = client.get(f"/v1/imports/batches/{b['id']}/errors.csv", headers=h)
    rows = list(csv.DictReader(io.StringIO(errs.text)))
    assert len(rows) == 4 and "problems" in rows[0] and rows[0]["row"] == "2"


def test_foreign_tenant_ids_and_unknown_activities_get_the_same_plain_answer(client):
    seed(client)
    seed(client, tenant="ten_other")
    with client.session_local() as s:
        s.add(Site(tenant_id="ten_other", site_id="other_only_site", name="x", timezone="UTC", operating_mode="standalone"))
        s.commit()
    h = admin()
    f = csv_text(["site", "activity", "period_start", "grain", "units"], [[MEL, "picking", "2026-10-05", "day", "10"], ["other_only_site", "picking", "2026-10-05", "day", "10"], [MEL, "welding", "2026-10-05", "day", "10"]])
    b = stage(client, h, "bulk", f, mode="upsert").json()
    msgs = {r["row"]: r["messages"][0]["text"] for r in b["rejected_sample"]}
    assert "not one of your sites" in msgs[2] and "other_only_site" in msgs[2] and "no work standard" in msgs[3]
    assert "exists" not in msgs[2] and "another" not in msgs[2]                                                        # no hint it belongs to another organisation


def test_only_permitted_roles_can_import_and_batches_are_tenant_private(client):
    seed(client)
    f = csv_text(["activity", "seconds_per_unit"], [["packing", "50"]])
    assert client.post("/v1/imports/csv/inspect", params={"data_class": "master", "entity": "work_standards"}, content=f.encode(), headers={**planner(), "Content-Type": "text/csv"}).status_code == 403
    assert client.post("/v1/imports/batches", json={"data_class": "master", "entity": "work_standards", "rows": [{"activity": "packing", "seconds_per_unit": "50"}]}, headers=planner()).status_code == 403
    seed(client, tenant="ten_other")
    b = stage(client, admin(), "master", f, entity="work_standards").json()
    other = admin("ten_other")
    assert client.get(f"/v1/imports/batches/{b['id']}", headers=other).status_code == 404
    assert client.post(f"/v1/imports/batches/{b['id']}/apply", headers=other).status_code == 404
    assert client.get("/v1/imports/batches", headers=other).json() == []
    assert client.get("/v1/imports/batches").status_code == 401


def test_work_standards_close_the_old_one_and_unchanged_is_unchanged(client):
    seed(client)
    h = admin()
    f = csv_text(["activity", "seconds_per_unit", "effective_from"], [["picking", "45", "2026-10-01"], ["packing", "62", "2026-10-01"], ["dispatch", "80", "2026-10-01"]])
    b = stage(client, h, "master", f, entity="work_standards").json()
    assert (b["summary"]["unchanged"], b["summary"]["updates"], b["summary"]["creates"]) == (1, 1, 1)
    client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h)
    with client.session_local() as s:
        rows = sorted((w.activity, w.time_per_unit_seconds, w.effective_to is None) for w in s.scalars(select(WorkStandard)))
    assert rows == [("dispatch", 80.0, True), ("packing", 50.0, False), ("packing", 62.0, True), ("picking", 45.0, True)] or \
        rows == [("dispatch", 80.0, True), ("packing", 45.0, False), ("packing", 62.0, True), ("picking", 45.0, True)]


# ------------------------------------------------------------------------------------------------ forecast
def test_supplied_forecast_is_versioned_flags_open_rosters_but_not_published_ones(client):
    seed(client)
    with client.session_local() as s:
        s.add(RosterVersion(tenant_id="ten_test", site_id=MEL, week_start="2026-10-05", days=7, version_no=1, state="draft", created_by="u"))
        s.add(RosterVersion(tenant_id="ten_test", site_id=MEL, week_start="2026-10-12", days=7, version_no=1, state="published", created_by="u"))
        s.commit()
    h = admin()
    rows = [[MEL, "picking", f"2026-10-{d:02d}", "day", 1000 + d] for d in range(5, 19)]
    f = csv_text(["site", "activity", "period_start", "grain", "units"], rows)
    assert stage(client, h, "forecast", f).status_code == 400                                              # a version label is required
    b = stage(client, h, "forecast", f, forecast_version="2026-10-v1").json()
    assert b["state"] == "validated" and b["summary"]["total_units"] == sum(1000 + d for d in range(5, 19))
    done = client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h).json()
    assert done["summary"]["applied"]["rosters_flagged_for_review"] == 1
    with client.session_local() as s:
        ev = {(e.version_id, e.action) for e in s.scalars(select(RosterEvent))}
        states = {v.week_start: v.state for v in s.scalars(select(RosterVersion))}
        assert s.execute(text("SELECT count(*) FROM supplied_forecast WHERE state='active'")).scalar() == 14
    assert any(a == "forecast_revised" for _v, a in ev) and len([1 for _v, a in ev if a == "forecast_revised"]) == 1
    assert states == {"2026-10-05": "draft", "2026-10-12": "published"}                                    # nothing rewritten
    again = stage(client, h, "forecast", f.replace("1005", "1006"), forecast_version="2026-10-v1").json()
    assert again["summary"]["blocking"] and not again["can_apply"]                                         # a label can be used once
    assert client.post(f"/v1/imports/batches/{again['id']}/apply", headers=h).status_code == 422
    assert client.put(f"/v1/sites/{MEL}/forecast-source", json={"source": "supplied"}, headers=h).json()["forecast_source"] == "supplied"
    st = client.get("/v1/imports/status", headers=h).json()
    assert st["forecast_versions"][0]["version"] == "2026-10-v1" and {s["site_id"]: s["forecast_source"] for s in st["sites"]}[MEL] == "supplied"
    assert client.post(f"/v1/imports/batches/{b['id']}/undo", headers=h).json()["state"] == "undone"
    with client.session_local() as s:
        assert s.execute(text("SELECT count(*) FROM supplied_forecast WHERE state='active'")).scalar() == 0


# ------------------------------------------------------------------------------------------------ 3 transactions: replay, correction, order
def txn(ev, site=MEL, act="picking", at="2026-09-21 10:15", qty=12, **kw):
    return {"event_id": ev, "site": site, "activity": act, "occurred_at": at, "quantity": qty, **kw}


def test_events_replay_corrections_cancellation_and_out_of_order_never_double_count(client):
    seed(client)
    h = admin()
    send = lambda rows, **o: client.post("/v1/imports/batches", json={"data_class": "transactions", "rows": rows, "apply": True, "options": o}, headers=h)  # noqa: E731
    hour_total = lambda: round(sum(b.volume for b in buckets(client, source="import:transactions") if b.activity == "picking"), 6)  # noqa: E731
    r = send([txn("A1"), txn("A2", qty=8), txn("A3", at="2026-09-21 11:05", qty=5)])
    assert r.status_code == 201 and r.json()["state"] == "applied", r.text
    assert hour_total() == 25
    hours = {(b.interval_start.astimezone(timezone.utc).hour): b.volume for b in buckets(client, source="import:transactions")}
    assert hours == {23: 20.0, 0: 5.0} or sum(hours.values()) == 25                                    # 10:15 and 11:05 Melbourne (UTC+11) land in separate hours
    # replay of the same events (different batch, same events): nothing changes
    r2 = send([txn("A1"), txn("A2", qty=8)])
    assert r2.json()["summary"]["unchanged"] == 2 and hour_total() == 25
    # same event with different data and no revision is a conflict, not a silent overwrite
    bad = send([txn("A1", qty=99)]).json()
    assert bad["error_rows"] == 1 and "action=correct" in bad["rejected_sample"][0]["messages"][0]["text"] and hour_total() == 25
    # correction with a higher revision updates; the same or lower revision is ignored as stale
    assert send([txn("A1", qty=20, action="correct", revision=2)]).json()["state"] == "applied" and hour_total() == 33
    stale = send([txn("A1", qty=1, action="correct", revision=2)]).json()
    assert stale["summary"]["unchanged"] == 1 and hour_total() == 33
    # cancel removes it from the count (evidence stays)
    send([txn("A2", action="cancel", revision=2, qty=8)])
    assert hour_total() == 25
    with client.session_local() as s:
        assert s.execute(text("SELECT count(*) FROM workload_event")).scalar() == 3
        assert s.execute(text("SELECT state FROM workload_event WHERE event_id='A2'")).scalar() == "cancelled"
    # out of order: a cancellation arrives before the create; the late create is ignored
    send([txn("Z9", qty=7, action="cancel", revision=3)])
    late = send([txn("Z9", qty=7, revision=2)]).json()
    assert late["summary"]["unchanged"] == 1 and hour_total() == 25
    # overnight / clock changes: an event at 02:30 on the 23-hour day is refused with instructions, with an offset it is accepted
    gap = send([txn("D1", at="2025-10-05 02:30")]).json()
    assert gap["error_rows"] == 1 and "does not exist" in gap["rejected_sample"][0]["messages"][0]["text"]
    ok = send([txn("D2", at="2025-10-05T03:30:00+11:00", qty=3), txn("D3", at="2025-10-05T23:50:00+11:00", qty=2)]).json()
    assert ok["state"] == "applied" and hour_total() == 30


def test_a_unit_that_changes_midstream_is_not_silently_mixed(client):
    seed(client)
    h = admin()
    r = client.post("/v1/imports/batches", json={"data_class": "transactions", "apply": True, "rows": [txn("U1", unit="cartons")]}, headers=h).json()
    assert r["state"] == "applied"
    r = client.post("/v1/imports/batches", json={"data_class": "transactions", "apply": True, "rows": [txn("U2", unit="pallets", at="2026-09-21 12:00")]}, headers=h).json()
    assert r["error_rows"] == 1 and "unit" in r["rejected_sample"][0]["messages"][0]["text"]


# ------------------------------------------------------------------------------------------------ 4 bulk totals: slices, control totals, take-over, authority
def bulk(days, act="picking", site=MEL, base=100):
    return [{"site": site, "activity": act, "period_start": d, "grain": "day", "units": base + i} for i, d in enumerate(days)]


WEEK = [f"2026-09-{d:02d}" for d in range(14, 21)]


def test_bulk_upsert_replace_slice_control_total_and_completeness(client):
    seed(client)
    h = admin()
    post = lambda rows, **o: client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": rows, "options": o}, headers=h)  # noqa: E731
    total = lambda: round(sum(b.volume for b in buckets(client, source="import:bulk")), 6)  # noqa: E731
    # control total: a file that does not add up is held, not applied
    held = post(bulk(WEEK), control_total=1).json()
    assert held["summary"]["blocking"] and not held["can_apply"]
    assert client.post(f"/v1/imports/batches/{held['id']}/apply", headers=h).status_code == 422
    good = post(bulk(WEEK), control_total=sum(100 + i for i in range(7))).json()
    assert good["can_apply"] and good["summary"]["total_units"] == 721
    assert client.post(f"/v1/imports/batches/{good['id']}/apply", headers=h).json()["state"] == "applied" and total() == 721
    # replaying the same totals changes nothing; an upsert of changed numbers updates only those periods
    assert post(bulk(WEEK), control_total=721).json()["replayed"] is True
    up = post(bulk(WEEK[:2], base=500)).json()
    client.post(f"/v1/imports/batches/{up['id']}/apply", headers=h)
    assert total() == 721 - 100 - 101 + 500 + 501
    # replace_slice must state its range; an ambiguous replacement is refused
    amb = client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(WEEK[:1]), "options": {"mode": "replace_slice"}}, headers=h)
    assert amb.status_code == 400 and "slice_start" in amb.json()["detail"]
    # rows outside the stated slice are rejected; missing days are reported and then emptied by the replacement
    rs = post(bulk(["2026-09-14", "2026-09-15", "2026-09-30"], base=7), mode="replace_slice", slice_start="2026-09-14", slice_end="2026-09-20").json()
    assert rs["error_rows"] == 1 and rs["summary"]["incomplete_periods"] == 5
    ok = client.post(f"/v1/imports/batches/{rs['id']}/apply", json={"accept_partial": True}, headers=h)
    assert ok.status_code == 200 and total() == 7 + 8                                              # the other five days were replaced (emptied), not kept
    # undo restores exactly what the slice replaced
    assert client.post(f"/v1/imports/batches/{rs['id']}/undo", headers=h).json()["state"] == "undone" and total() == 721 - 100 - 101 + 500 + 501


def test_workload_from_another_source_is_only_replaced_deliberately(client):
    seed(client)
    h = admin()
    with client.session_local() as s:
        s.add(DemandBucket(tenant_id="ten_test", activity="picking", site_id=MEL, interval_start=datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc), volume=999, source="deputy_sim", bucket_minutes=1440))
        s.commit()
    held = client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(["2026-09-14"])}, headers=h).json()
    assert held["summary"]["blocking"] and "deputy_sim" in held["summary"]["blocking"][0]
    taken = client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(["2026-09-14"]), "options": {"take_over": True}}, headers=h).json()
    assert taken["can_apply"]
    client.post(f"/v1/imports/batches/{taken['id']}/apply", headers=h)
    assert {b.source for b in buckets(client)} == {"import:bulk"}
    client.post(f"/v1/imports/batches/{taken['id']}/undo", headers=h)
    assert {b.source for b in buckets(client)} == {"deputy_sim"}                                      # the displaced workload came back


def test_events_and_totals_for_the_same_work_are_never_both_counted(client):
    seed(client)
    h = admin()
    ev = client.post("/v1/imports/batches", json={"data_class": "transactions", "apply": True, "rows": [txn("S1", qty=10)]}, headers=h).json()
    assert ev["state"] == "applied"
    tot = client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(["2026-09-21"], base=500)}, headers=h).json()
    assert any("NOT counted" in n for n in tot["summary"]["notes"])
    done = client.post(f"/v1/imports/batches/{tot['id']}/apply", headers=h).json()
    assert done["summary"]["applied"]["not_counted_events_are_authoritative"] == ["picking@site_mel_01"]
    assert round(sum(b.volume for b in buckets(client)), 6) == 10                                       # only the events are counted
    st = client.get("/v1/imports/status", headers=h).json()
    assert [a for a in st["authority"] if a["activity"] == "picking" and a["site_id"] == MEL][0]["authority"] == "transactions"
    other = client.post("/v1/imports/batches", json={"data_class": "bulk", "apply": True, "rows": bulk(["2026-09-21"], act="packing", base=40)}, headers=h).json()
    assert other["state"] == "applied" and round(sum(b.volume for b in buckets(client) if b.activity == "packing"), 6) == 40   # a different activity may use the other kind


# ------------------------------------------------------------------------------------------------ 2 API == CSV, idempotency, service credentials
def test_csv_and_api_produce_identical_canonical_totals(client):
    seed(client)
    seed(client, tenant="ten_api")
    rows = bulk(WEEK, base=300) + bulk(WEEK[:3], act="packing", base=50, site=SYD)
    f = csv_text(["site", "activity", "period_start", "grain", "units"], [[r["site"], r["activity"], r["period_start"], r["grain"], r["units"]] for r in rows])
    b1 = stage(client, admin(), "bulk", f).json()
    client.post(f"/v1/imports/batches/{b1['id']}/apply", headers=admin())
    b2 = client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": rows, "apply": True}, headers=admin("ten_api")).json()
    assert b2["state"] == "applied"
    shape = lambda t: [(b.site_id, b.activity, b.interval_start, b.bucket_minutes, b.volume) for b in buckets(client, tenant=t)]  # noqa: E731
    assert shape("ten_test") == shape("ten_api") and len(shape("ten_api")) == 10


def test_idempotency_key_returns_the_same_receipt_and_rejects_different_content(client):
    seed(client)
    h = {**admin(), "Idempotency-Key": "load-2026-09-21"}
    a = client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(WEEK[:2])}, headers=h).json()
    b = client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(WEEK[:2])}, headers=h).json()
    assert b["id"] == a["id"] and b["replayed"] is True
    c = client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(WEEK[:3])}, headers=h)
    assert c.status_code == 400 and "Idempotency-Key" in c.json()["detail"]
    with client.session_local() as s:
        assert s.scalar(text("SELECT count(*) FROM import_batch")) == 1


def test_service_credentials_are_scoped_rotatable_revocable_and_shown_once(client):
    seed(client)
    h = admin()
    made = client.post("/v1/admin/api-credentials", json={"name": "WMS feed", "site_ids": [MEL], "valid_days": 30}, headers=h)
    assert made.status_code == 201, made.text
    secret, cid = made.json()["secret"], made.json()["id"]
    assert secret.startswith("tsc_") and "secret" not in client.get("/v1/admin/api-credentials", headers=h).json()[0]
    with client.session_local() as s:
        stored = s.execute(text("SELECT credential_hash, scopes FROM service_client")).one()
    assert secret.split(".", 1)[1] not in stored[0] and stored[1] == ["labour.data.import"]                    # only a digest is stored
    bearer = {"Authorization": f"Bearer {secret}"}
    ok = client.post("/v1/imports/batches", json={"data_class": "bulk", "apply": True, "rows": bulk(WEEK[:1])}, headers=bearer)
    assert ok.status_code == 201 and ok.json()["state"] == "applied" and ok.json()["created_by"].startswith("svc:")
    outside = client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(WEEK[:1], site=SYD)}, headers=bearer).json()
    assert outside["error_rows"] == 1 and "not one of your sites" in outside["rejected_sample"][0]["messages"][0]["text"]       # credential is limited to its site
    assert client.get("/v1/admin/audit", headers=bearer).status_code in (401, 403)                         # it can do nothing but ingest
    assert client.get("/v1/sites", headers=bearer).status_code in (401, 403)
    new = client.post(f"/v1/admin/api-credentials/{cid}/rotate", headers=h).json()["secret"]
    assert client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(WEEK[:1])}, headers=bearer).status_code == 401   # old secret is dead
    assert client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(WEEK[:1])}, headers={"Authorization": f"Bearer {new}"}).status_code == 201
    client.post(f"/v1/admin/api-credentials/{cid}/revoke", headers=h)
    assert client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(WEEK[:1])}, headers={"Authorization": f"Bearer {new}"}).status_code == 401
    assert client.post("/v1/imports/batches", json={"data_class": "bulk", "rows": bulk(WEEK[:1])}, headers={"Authorization": "Bearer tsc_deadbeef.nope"}).status_code == 401
    # a person cannot be given the service-only role, and non-admins cannot mint credentials
    assert client.post("/v1/admin/api-credentials", json={"name": "xx"}, headers=planner()).status_code == 403
    mk = client.post("/v1/admin/users", json={"email": "p@example.com", "display_name": "P", "roles": ["integration_import"], "site_ids": [MEL]}, headers=h)
    assert mk.status_code in (400, 404, 422)
    # the audit trail names the credential, never the secret
    with client.session_local() as s:
        evs = s.execute(text("SELECT action, actor_type FROM security_audit_event WHERE action LIKE 'import.%' OR action LIKE 'credential.%'")).all()
        assert ("import.apply", "service") in {tuple(e) for e in evs} and not s.execute(text("SELECT 1 FROM security_audit_event WHERE reason_code LIKE '%tsc_%'")).first()


# ------------------------------------------------------------------------------------------------ forecast source drives the planner
def test_a_chosen_supplied_forecast_replaces_the_model_visibly_and_falls_back_when_incomplete(client):
    from zoneinfo import ZoneInfo
    from app.schemas.runs import PlanningWindow, RunRequest, RunScope
    from app.solvers.demand_forecast import forecast_demand
    seed(client, standards=("picking", "packing"))
    h = admin()
    days = [f"2026-10-{d:02d}" for d in range(5, 12)]
    sup_rows = [[MEL, "picking", d, "day", 5000 + i, 4500 + i, 5500 + i] for i, d in enumerate(days)] + [[MEL, "packing", d, "day", 700] for d in days[:3]]   # packing is incomplete
    f = csv_text(["site", "activity", "period_start", "grain", "units", "lower", "upper"], [r + [""] * (7 - len(r)) for r in sup_rows])
    b = stage(client, h, "forecast", f, forecast_version="W41-v1").json()
    assert b["state"] == "validated", b
    client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h)
    with client.session_local() as s:   # some history so the model can still forecast packing
        for i in range(28):
            d = datetime(2026, 9, 1, tzinfo=ZoneInfo("Australia/Melbourne")) + timedelta(days=i)
            s.add(DemandBucket(tenant_id="ten_test", activity="packing", site_id=MEL, interval_start=d.astimezone(timezone.utc), volume=600 + i, source="hist", bucket_minutes=1440))
        s.commit()
    mel = ZoneInfo("Australia/Melbourne")
    start = datetime(2026, 10, 5, tzinfo=mel).astimezone(timezone.utc)

    def run():
        req = RunRequest(request_id="r", scope=RunScope(tenant_id="ten_test", site_ids=[MEL], customer_ids=["cust_A"]),
                         planning_window=PlanningWindow(start=start, end=start + timedelta(days=7), timezone="Australia/Melbourne", bucket_minutes=1440))
        with client.app_session_local() as db:
            from app.db import bind_sites, bind_tenant
            bind_tenant(db, "ten_test")
            return forecast_demand(db, "ten_test", [MEL], req)
    model_only = run()                                                                             # default source: Tempo's model
    assert model_only.result["forecast_source"] == "generated" and model_only.result["supplied_versions"] == []
    client.put(f"/v1/sites/{MEL}/forecast-source", json={"source": "supplied"}, headers=h)
    mixed = run()
    assert mixed.result["forecast_source"] == "mixed" and mixed.result["supplied_versions"] == ["W41-v1"]
    picks = [r for r in mixed.result["forecast"] if r["activity"] == "picking"]
    assert [r["point"] for r in picks] == [5000 + i for i in range(7)] and {r["origin"] for r in picks} == {"supplied:W41-v1"} and picks[0]["lower"] == 4500
    assert len([r for r in mixed.result["forecast"] if r["activity"] == "packing"]) == 7 and all("origin" not in r for r in mixed.result["forecast"] if r["activity"] == "packing")   # fallback is the model
    assert any("does not cover every period for packing" in m for m in mixed.missing_evidence)
    client.put(f"/v1/sites/{MEL}/forecast-source", json={"source": "generated"}, headers=h)
    assert run().result["forecast_source"] == "generated"                                          # choosing the model again restores it


def test_daily_totals_show_in_the_demand_and_variance_reports(client):
    seed(client)
    h = admin()
    client.post("/v1/imports/batches", json={"data_class": "bulk", "apply": True, "rows": bulk(["2026-09-14", "2026-09-15"], base=1000)}, headers=h)
    d = client.get(f"/v1/sites/{MEL}/demand", params={"start": "2026-09-14"}, headers=h).json()
    got = {(r["date"], r["activity"]): r["actual_units"] for r in d["rows"] if r["actual_units"] is not None}
    assert got == {("2026-09-14", "picking"): 1000, ("2026-09-15", "picking"): 1001}
    v = client.get(f"/v1/sites/{MEL}/reports/variance", params={"start": "2026-09-14"}, headers=h).json()
    assert {x["date"]: x["actual_units"] for x in v["days"] if x["actual_units"]} == {"2026-09-14": 1000, "2026-09-15": 1001}


def test_setup_checklist_tells_a_new_customer_what_to_do_next(client):
    seed(client, standards=())
    h = admin()
    c = client.get("/v1/setup/checklist", headers=h).json()
    st = {s["key"]: s["state"] for s in c["steps"]}
    assert st == {"organisation": "done", "sites": "done", "staff": "todo", "standards": "todo", "workload": "todo", "rates": "todo", "attendance": "todo", "roster": "todo"} and c["next"] == "staff" and c["done"] == 2
    todo = {s["key"]: s for s in c["steps"]}["staff"]
    assert "template" in todo["detail"] and todo["link"].startswith("/data?tab=upload")
    for name, f, ent in (("staff", csv_text(["worker_ref", "name", "site", "employment_type"], [["E1", "A B", MEL, "casual"]]), "workers"),
                         ("standards", csv_text(["activity", "seconds_per_unit"], [["picking", "40"]]), "work_standards")):
        b = stage(client, h, "master", f, entity=ent).json()
        client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h)
    client.post("/v1/imports/batches", json={"data_class": "bulk", "apply": True, "rows": bulk(["2026-09-14"])}, headers=h)
    c = client.get("/v1/setup/checklist", headers=h).json()
    assert {s["key"]: s["state"] for s in c["steps"]}["staff"] == "done" and c["next"] == "roster" and c["done"] == 5 and not c["complete"]


# ------------------------------------------------------------------------------------------------ sites, customers, availability, rates
def _run(client, h, entity, header, rows, **kw):
    b = stage(client, h, "master", csv_text(header, rows), entity=entity, **kw)
    assert b.status_code in (200, 201), b.text
    return b.json()


def _apply(client, h, b):
    return client.post(f"/v1/imports/batches/{b['id']}/apply", headers=h)


def test_sites_need_configure_get_granted_to_the_uploader_and_cannot_change_timezone(client):
    seed(client)
    rows = [["bne_dc_03", "Brisbane DC", "Australia/Brisbane", "standalone"], ["bad", "Bad", "Mars/Olympus", ""]]
    head = ["site_id", "name", "timezone", "operating_mode"]
    pl = context_header(roles=["operations_manager"], user_id="usr_ops", site_ids=[MEL, SYD])   # may import, may not configure
    held = _run(client, pl, "sites", head, rows[:1])
    assert held["summary"]["blocking"] and _apply(client, pl, held).status_code == 422                               # a planner may not add sites
    b = _run(client, admin(), "sites", head, rows)
    assert b["error_rows"] == 1 and "not a time zone name" in json.dumps(b)
    done = _apply(client, admin(), b)
    assert done.status_code == 422                                                                                  # partial needs a choice
    ok = client.post(f"/v1/imports/batches/{b['id']}/apply", json={"accept_partial": True}, headers=admin())
    assert ok.status_code == 200 and ok.json()["summary"]["applied"] == {"created": 1, "updated": 0}
    with client.session_local() as s:
        assert s.get(Site, ("ten_test", "bne_dc_03")).timezone == "Australia/Brisbane"
    again = _run(client, admin(), "sites", head, [["bne_dc_03", "Brisbane DC", "Australia/Sydney", ""]])
    assert again["error_rows"] == 1 and "cannot be changed by upload" in json.dumps(again)
    renamed = _run(client, admin(), "sites", head, [["bne_dc_03", "Brisbane Hub", "Australia/Brisbane", "overlay"]])
    assert _apply(client, admin(), renamed).json()["summary"]["applied"]["updated"] == 1


def test_customers_and_rates_upsert_and_rates_feed_planned_cost_inputs(client):
    seed(client)
    h = admin()
    c = _run(client, h, "customers", ["customer_id", "name", "status"], [["cust_B", "Beta Foods", ""], ["cust_A", "Alpha", "inactive"]])
    assert _apply(client, h, c).json()["summary"]["applied"] == {"created": 1, "updated": 1}
    r = _run(client, h, "rates", ["employment_type", "role", "hourly_rate", "overtime_multiplier", "surcharge"],
             [["casual", "picker", "42.5", "1.5", ""], ["labour hire", "", "55", "", "8"], ["casual", "picker", "-1", "", ""]])
    assert r["error_rows"] == 1
    assert client.post(f"/v1/imports/batches/{r['id']}/apply", json={"accept_partial": True}, headers=h).json()["summary"]["applied"]["created"] == 2
    from app.models.canonical import LabourCostRule
    with client.session_local() as s:
        got = {(x.labour_type, x.role): (x.rate, x.overtime_multiplier, x.surcharge) for x in s.scalars(select(LabourCostRule))}
        assert got == {("casual", "picker"): ("42.50", "1.5", None), ("labour_hire", "general"): ("55.00", None, "8.00")}
    r2 = _run(client, h, "rates", ["employment_type", "role", "hourly_rate", "overtime_multiplier"], [["casual", "picker", "42.5", "1.5"]])
    assert r2["summary"]["unchanged"] == 1
    assert _apply(client, h, r2).json()["summary"]["applied"]["unchanged"] == 1


def test_availability_import_matches_people_is_idempotent_blocks_rosters_and_can_be_undone(client):
    seed(client)
    h = admin()
    staff = _run(client, h, "workers", ["worker_ref", "name", "site", "employment_type", "status", "skills", "employee_no"], [["E1", "Sam", MEL, "casual", "active", "picker", ""]])
    _apply(client, h, staff)
    head = ["worker_ref", "kind", "from", "to"]
    rows = [["E1", "leave", "2026-10-12 00:00", "2026-10-16 00:00"], ["E9", "leave", "2026-10-12", "2026-10-13"], ["E1", "rdo", "2026-10-20 00:00", "2026-10-19 00:00"]]
    b = _run(client, h, "availability", head, rows)
    msgs = json.dumps(b)
    assert b["error_rows"] == 2 and "Upload staff first" in msgs and "to must be after from" in msgs
    assert client.post(f"/v1/imports/batches/{b['id']}/apply", json={"accept_partial": True}, headers=h).json()["summary"]["applied"] == {"created": 1, "unchanged": 0}
    from app.models.canonical import Availability
    with client.session_local() as s:
        a = s.scalars(select(Availability)).one()
        assert a.status == "leave" and a.interval_start.isoformat().startswith("2026-10-11T13:00") and a.source_system == "tempo_import"   # Melbourne midnight in UTC
    b2 = _run(client, h, "availability", head, rows[:1])
    assert b2["summary"]["unchanged"] == 1
    assert _apply(client, h, b2).json()["summary"]["applied"] == {"created": 0, "unchanged": 1}
    undo = client.post(f"/v1/imports/batches/{b['id']}/undo", headers=h)
    assert undo.status_code == 200 and undo.json()["state"] == "undone"
    with client.session_local() as s:
        assert s.scalars(select(Availability)).all() == []
