"""Arch acceptance: the specific original data issues named in the brief — mismatched task-name
casing across sheets, duplicate area/zone names, an unqualified supervisor, an order dated outside
the planning horizon, an empty optional sheet, and a template's own example row left in an upload —
verified through the real import and run-creation APIs, not just the pure validator functions.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.imports.contracts import CONTRACTS, template_csv

from .test_imports import MEL, admin, csv_text, seed, stage
from .test_integration_order_schedule import _body, _get, _order, _process, _rate, _run, _staff, _window
from .test_run_endpoint import _headers
from .test_stage2_order_workload import apply as _apply_batch


def apply(client, h, b):
    return _apply_batch(client, h, b)


WINDOW = _window("2026-10-11T12:00:00Z", "2026-10-13T12:00:00Z")


def test_activity_name_casing_mismatch_across_sheets_is_normalised_not_rejected(client):
    """A work standard uploaded as 'picking' and a process step uploaded as 'Picking' are the SAME
    activity — a customer's own sheets routinely differ only in case, and that must not be treated as
    a spelling error (same normalisation already applied to `unit`)."""
    seed(client)
    h = admin()
    mixed_case_step = csv_text(["site", "process_code", "customer_id"], [[MEL, "p1", ""]])
    apply(client, h, stage(client, h, "master", mixed_case_step, entity="process_templates").json())
    staged = stage(client, h, "master", csv_text(["site", "process_code", "sequence", "activity"], [[MEL, "p1", "1", "Picking"]]), entity="process_steps").json()
    assert staged["error_rows"] == 0, staged
    apply(client, h, staged)
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)  # the personal rate is keyed on the LOWERCASE activity
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 300, "p1")
    result = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    assert result["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.5)  # the rate matched despite the casing difference


def test_duplicate_zone_names_import_as_distinct_zones(client):
    """Two zones sharing the same display name (a realistic warehouse data issue — e.g. two 'Pick
    Area' zones in different aisles) must not be merged or mis-mapped; `zone_id` is the real key."""
    seed(client)
    h = admin()
    zones = csv_text(["site", "zone_id", "zone_name"], [[MEL, "PICK_A", "Pick Area"], [MEL, "PICK_B", "Pick Area"]])
    done = apply(client, h, stage(client, h, "master", zones, entity="zones").json())
    assert done["summary"]["applied"] == {"created": 2, "updated": 0}
    with client.session_local() as s:
        from app.models.directory import Zone
        rows = list(s.scalars(select(Zone).where(Zone.tenant_id == "ten_test", Zone.site_id == MEL, Zone.name == "Pick Area")))
        assert {r.zone_id for r in rows} == {"PICK_A", "PICK_B"}  # both kept, distinct by zone_id


def test_unqualified_supervisor_requirement_reports_a_coverage_gap_not_a_silent_pick(client):
    """An indirect-coverage role requiring a skill nobody holds (an 'unqualified supervisor' scenario
    — the site has staff, but none qualified) must surface as a reported gap, never silently pick an
    unqualified worker or silently produce zero without saying why."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])  # no 'supervisor' skill granted
    indirect = csv_text(["site", "role", "weekday", "start_time", "end_time", "headcount"], [[MEL, "supervisor", "monday", "06:00", "14:00", "1"]])
    apply(client, h, stage(client, h, "master", indirect, entity="indirect_headcount").json())
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 06:00", "2026-10-12 14:00", 100, "p1")
    result = _get(client, _run(client, _body(WINDOW))["run_id"])["result"]
    gaps = result["indirect_coverage_gaps"]
    assert any(g["role"] == "supervisor" and g["reason"] == "missing_qualified_workers" for g in gaps)


def test_order_outside_planning_horizon_is_excluded_not_silently_scheduled(client):
    """An order whose window does not overlap the run's planning window at all must simply not
    appear — it is neither scheduled nor silently dropped without explanation; it is absent because
    it is genuinely out of scope for this run."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-IN", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p1")        # inside WINDOW
    _order(client, h, "SO-OUT", "2026-11-01 09:00", "2026-11-01 12:00", 100, "p1")       # three weeks outside WINDOW
    run = _get(client, _run(client, _body(WINDOW))["run_id"])
    refs = {o["order_ref"] for o in run["result"]["orders"]}
    assert refs == {"SO-IN"}  # SO-OUT is outside the horizon and correctly excluded from this run

    # ...but not WITHOUT a trace: a visible exclusion summary names it, both in the result payload
    # and in the run's explanation, so a reviewer never has to wonder where a known order went.
    excluded = run["result"]["orders_outside_horizon"]
    assert len(excluded) == 1 and excluded[0]["order_ref"] == "SO-OUT"
    assert any("SO-OUT" in m and "excluded" in m for m in run["explanation"]["missing_evidence"])


def test_order_entirely_outside_horizon_is_named_even_when_the_run_is_rejected(client):
    """The same visible-exclusion guarantee holds even in the edge case where EVERY open order is
    outside the window — InsufficientData never persists a run, but its own message must still name
    what exists and why it was excluded, not just say 'nothing found'."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-OUT", "2026-11-01 09:00", "2026-11-01 12:00", 100, "p1")  # the ONLY order, and it's outside WINDOW
    body = _body(WINDOW)
    body["request_id"] = str(uuid.uuid4())
    r = client.post("/v1/optimisations/order_fulfillment", json=body, headers=_headers())
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "SO-OUT" in detail and "outside" in detail


def test_empty_optional_sheet_upload_is_rejected_cleanly_not_crashed(client):
    """An optional master-data sheet (e.g. Absenteeism) left with only its header row is a realistic
    'nothing to configure yet' upload — Tempo correctly treats it as not worth uploading at all
    (an actionable 400, not a 500 or a silent no-op), and the setup checklist simply leaves that
    optional step undone rather than erroring the whole import flow."""
    seed(client)
    h = admin()
    header_only = "site,activity,absence_pct\n"
    ins = client.post("/v1/imports/csv/inspect", params={"data_class": "master", "entity": "absenteeism"}, content=header_only.encode(), headers={**h, "Content-Type": "text/csv"})
    assert ins.status_code == 400
    assert "no data rows" in ins.json()["detail"]


def test_v1_shaped_work_standards_csv_still_imports_without_the_new_optional_columns(client):
    """v1 compatibility: a work_standards file with none of this programme's additive columns
    (function, flow, required_skill) must still import cleanly — those columns are optional."""
    seed(client)
    h = admin()
    v1 = csv_text(["activity", "seconds_per_unit"], [["receiving", "30"]])  # no function/flow/required_skill at all
    done = apply(client, h, stage(client, h, "master", v1, entity="work_standards").json())
    assert done["summary"]["applied"]["created"] == 1
    with client.session_local() as s:
        from app.models.canonical import WorkStandard
        ws = s.scalar(select(WorkStandard).where(WorkStandard.tenant_id == "ten_test", WorkStandard.activity == "receiving"))
        assert ws.function is None and ws.flow is None and ws.required_skill is None


def test_template_example_row_requires_an_explicit_apply_before_becoming_real_data(client):
    """Preserve ignored example rows: investigated whether Tempo should auto-detect and silently
    discard a row that matches a downloaded template's own example values. Rejected — a real
    customer row can legitimately match every example value (plausible activity names, round
    numbers, common dates), and three existing tests in this suite do exactly that; a content-based
    guess would then silently discard real data, which is worse than the problem it solves. Instead,
    the template's example row is just an ordinary valid row (`test_every_template_example_row_
    passes_its_own_validator`) that — like every other staged row — only becomes real data if a
    person explicitly reviews the staged preview and calls apply; staging alone never does."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1042"])  # the contract's own example worker_ref, so the example row is fully valid, not merely well-shaped
    c = CONTRACTS[("master", "worker_activity_rates")]
    csv_with_example_row = template_csv(c)  # header + the contract's own example row, verbatim
    staged = stage(client, h, "master", csv_with_example_row, entity="worker_activity_rates").json()
    assert staged["ok_rows"] == 1  # a well-formed row, staged for review — not yet applied
    with client.session_local() as s:
        from app.models.imports import ImportBatch
        assert s.get(ImportBatch, staged["id"]).state == "validated"  # not "applied" — nothing is real data until a person says so


def test_plain_csv_rows_are_preserved_regardless_of_whether_they_match_an_example(client):
    """Structural confirmation for CSV (Tempo's only import format — see Stage 0: "Current Tempo does
    not import Excel workbooks at all"): every non-blank data row after the header is kept, whatever
    its content. A row matching the example exactly, a row that doesn't, and a genuinely blank row are
    all handled by POSITION (header=row 1, blank rows skipped), never by guessing a row's intent from
    its values."""
    seed(client)
    h = admin()
    c = CONTRACTS[("master", "day_rates")]
    example = [f.example for f in c.fields]  # matches the template's own example exactly
    different = ["packing", "tuesday", "77"]
    rows_csv = ",".join(c.names) + "\n" + ",".join(example) + "\n\n" + ",".join(different) + "\n"  # example row, a blank line, a different row
    staged = stage(client, h, "master", rows_csv, entity="day_rates").json()
    assert staged["ok_rows"] == 2  # BOTH data rows kept — the example-matching one is not specially dropped; the blank one is (by position, not content)


def test_activity_name_that_does_not_exist_anywhere_produces_an_actionable_validation_error(client):
    """Item 1: an abbreviated or inconsistent activity name across sheets (e.g. a process step
    uploaded as 'Replen' when the work standard was defined as 'replenishment' — not a casing
    difference, a genuinely different string) is not silently accepted, auto-mapped, or merged. Tempo
    has no activity-value synonym table, so this is the 'explicit validation error' half of the
    brief's 'explicit mapping requirement OR validation error' — and it names the fix."""
    seed(client)
    h = admin()
    std = csv_text(["activity", "seconds_per_unit"], [["replenishment", "40"]])
    apply(client, h, stage(client, h, "master", std, entity="work_standards").json())
    apply(client, h, stage(client, h, "master", csv_text(["site", "process_code", "customer_id"], [[MEL, "p1", ""]]), entity="process_templates").json())
    staged = stage(client, h, "master", csv_text(["site", "process_code", "sequence", "activity"], [[MEL, "p1", "1", "Replen"]]), entity="process_steps")
    assert staged.json()["error_rows"] == 1
    with client.session_local() as s:
        from app.models.imports import ImportRow
        row = s.scalar(select(ImportRow).where(ImportRow.batch_id == staged.json()["id"]))
        assert any("has no work standard" in m["text"] for m in row.messages)  # actionable: says exactly what to add


def test_order_fulfillment_run_with_no_optional_entities_configured_at_all_completes(client):
    """Empty optional sheets can be omitted cleanly: a run with NONE of equipment, headcount_limits,
    indirect_headcount, absenteeism, productivity_loss, staging, day_rates, award_rules or
    weekly_availability ever uploaded must still complete normally — every one of those entities is
    optional, not a hidden prerequisite."""
    seed(client)
    h = admin()
    _staff(client, h, ["E1"])
    _rate(client, h, "E1", "picking", 100)
    _process(client, h, "p1", [(1, "picking", 0, "", "")])
    _order(client, h, "SO-1", "2026-10-12 09:00", "2026-10-12 12:00", 100, "p1")
    run = _get(client, _run(client, _body(WINDOW))["run_id"])
    assert run["status"] in ("completed", "completed_with_warnings")
    assert run["result"]["orders"][0]["shortfall_quantity"] == pytest.approx(0, abs=0.01)
