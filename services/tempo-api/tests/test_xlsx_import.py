"""Version-aware v1/v2 workbook (.xlsx) import, alongside CSV (brief: "retain CSV support without
content-based row deletion"). Built from the source-workbook review's literal, stated facts:

- Ordinary data sheets: header row 1, metadata rows 2-3, example row 4, data from row 5.
- Rules/reference sheets use a different, simpler layout (header row 1, data from row 2).
- v1 uses `seconds_per_unit`, `skill_code`, and a "Shift Patterns" sheet.
- v2 uses `standard_rate_per_hour`, `role`, and "Shift Templates"/"Shift Breaks" sheets.

None of this has been checked against the actual supplied v1/v2 files — this session was not given
them. These tests instead verify the above facts against LOCAL fixtures built to match them exactly;
see app/imports/xlsx.py's module docstring for exactly what remains unverified.
"""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models.canonical import Worker, WorkStandard
from app.models.constraints import AwardRule
from app.models.orders import DayRate

from .test_imports import MEL, admin, seed


def _xlsx_bytes(sheets: dict[str, list[list[str]]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------------------------- structural layout + atomic apply
WORKERS_SHEET = [
    ["Employee ID", "Full Name", "Location", "Type"],          # row 1: header
    ["Fill in your own staff below. Do not delete this row."],  # row 2: guidance (wrong shape entirely — proves position, not shape, decides)
    [],                                                          # row 3: blank
    ["E1042", "Sam Taylor", MEL, "casual"],                      # row 4: the template's own EXAMPLE — a fully well-formed row, structurally ignored
    ["E1", "Worker E1", MEL, "permanent"],                       # row 5: real data
    ["E1042", "Sam Taylor", MEL, "casual"],                      # row 6: real data that happens to match the example EXACTLY — must still be imported
]

WORK_STANDARDS_SHEET_V1 = [
    ["activity", "seconds_per_unit"],
    ["Guidance: seconds per unit of work."],
    [],
    ["picking", "45"],   # row 4: example — structurally ignored even though it's a plausible real value
    ["packing", "60"],   # row 5: real data
]


def test_recognised_sheets_are_applied_atomically_in_dependency_order_with_row_4_ignored(client):
    seed(client, standards=())  # no pre-seeded work standards — this workbook supplies its own
    h = admin()
    data = _xlsx_bytes({"Workers": WORKERS_SHEET, "Work Standards": WORK_STANDARDS_SHEET_V1, "Notes": [["not a recognised entity"]]})

    inspect = client.post("/v1/imports/xlsx/inspect", content=data, headers={**h, "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
    assert inspect.status_code == 200, inspect.text
    by_sheet = {s["sheet"]: s for s in inspect.json()["sheets"]}
    assert by_sheet["Workers"]["recognised"] is True and by_sheet["Workers"]["entity"] == "workers"
    assert by_sheet["Work Standards"]["recognised"] is True and by_sheet["Work Standards"]["entity"] == "work_standards"
    assert by_sheet["Notes"]["recognised"] is False
    assert by_sheet["Workers"]["row_count"] == 2  # rows 5 and 6 only — NOT the guidance row, the blank row, or row 4's example

    staged = client.post("/v1/imports/xlsx/stage", content=data, headers={**h, "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
    assert staged.status_code == 201, staged.text
    body = staged.json()
    assert body["skipped_sheets"] == ["Notes"]
    by_entity = {s["entity"]: s for s in body["applied"]}
    ranks = [s["entity"] for s in body["applied"]]
    assert ranks.index("work_standards") < ranks.index("workers")  # dependency order, not file order

    assert by_entity["work_standards"]["batch"]["ok_rows"] == 1  # only "packing" (row 5) — "picking" (row 4) was structurally ignored
    assert by_entity["workers"]["batch"]["ok_rows"] == 2          # E1 and the example-matching E1042, BOTH real (row 5 and row 6)

    # ATOMIC: both sheets are already applied, with no separate /imports/batches/{id}/apply call.
    with client.session_local() as s:
        activities = {w.activity for w in s.scalars(select(WorkStandard).where(WorkStandard.tenant_id == "ten_test"))}
        assert activities == {"packing"}  # "picking" (the example row's activity) was never created
        refs = {w.source_ref for w in s.scalars(select(Worker).where(Worker.tenant_id == "ten_test", Worker.source_system == "tempo_import"))}
        assert refs == {"E1", "E1042"}  # E1042 WAS imported from row 6 — matching the example's content didn't exclude it


def test_unrecognised_sheet_is_reported_not_silently_dropped(client):
    seed(client)
    h = admin()
    data = _xlsx_bytes({"Mystery Tab": [["a", "b"], [], [], [], ["1", "2"]]})
    inspect = client.post("/v1/imports/xlsx/inspect", content=data, headers={**h, "Content-Type": "application/octet-stream"})
    assert inspect.status_code == 200
    assert inspect.json()["sheets"] == [{"sheet": "Mystery Tab", "recognised": False, "row_count": 1}]

    staged = client.post("/v1/imports/xlsx/stage", content=data, headers={**h, "Content-Type": "application/octet-stream"})
    assert staged.status_code == 201
    assert staged.json() == {"applied": [], "skipped_sheets": ["Mystery Tab"]}


def test_not_a_real_workbook_is_rejected_cleanly(client):
    h = admin()
    r = client.post("/v1/imports/xlsx/inspect", content=b"this is not an xlsx file", headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 400
    assert "not a readable" in r.json()["detail"]


def test_cross_sheet_reference_resolves_within_one_workbook_upload(client):
    """Preserving sheet relationships means a LATER sheet can reference an entity an EARLIER sheet in
    the SAME workbook defines — process steps naming a process template from the Process Templates
    sheet above it, in one upload, with no second pass required."""
    seed(client)
    h = admin()
    templates_sheet = [["site", "process_code", "customer_id"], [], [], [], [MEL, "p1", ""]]
    steps_sheet = [["site", "process_code", "sequence", "activity"], [], [], [], [MEL, "p1", "1", "picking"]]
    data = _xlsx_bytes({"Process Templates": templates_sheet, "Process Steps": steps_sheet})
    staged = client.post("/v1/imports/xlsx/stage", content=data, headers={**h, "Content-Type": "application/octet-stream"})
    assert staged.status_code == 201, staged.text
    by_entity = {s["entity"]: s for s in staged.json()["applied"]}
    assert by_entity["process_steps"]["batch"]["ok_rows"] == 1  # resolved the process_code defined earlier in the SAME upload


def test_no_partial_import_left_behind_when_a_later_sheet_fails(client):
    """A workbook where an EARLIER sheet is perfectly valid but a LATER one fails must leave NOTHING
    applied — not even the earlier, individually-valid sheet."""
    seed(client)
    h = admin()
    good_sites = [["site_id", "name", "timezone"], [], [], [], ["bad_site_01", "Bad Site", "Australia/Melbourne"]]
    bad_customers = [["customer_id", "name"], [], [], [], ["", "Missing the required ID"]]  # customer_id required and blank — a genuine error row
    data = _xlsx_bytes({"Sites": good_sites, "Customers": bad_customers})
    staged = client.post("/v1/imports/xlsx/stage", content=data, headers={**h, "Content-Type": "application/octet-stream"})
    assert staged.status_code >= 400  # the whole workbook is refused

    with client.session_local() as s:
        from app.models.directory import Site
        assert s.scalar(select(Site).where(Site.tenant_id == "ten_test", Site.site_id == "bad_site_01")) is None  # the EARLIER, individually-valid sheet was NOT left applied


# --------------------------------------------------------------------------------------------- rules/reference sheet layout
def test_rules_reference_sheet_currently_falls_back_to_the_confirmed_data_layout(client):
    """CORRECTED: an earlier version of this importer assumed Rules/reference sheets share ONE
    uniform layout (header row 1, data from row 2, no metadata/example rows). That assumption was
    wrong — the source-workbook review found each Rules sheet carries its OWN requirements, guidance
    and instruction/example rows before the real entries, not a shared shape. Lacking the actual
    per-sheet row numbers, `app.imports.xlsx.row_layout()` now falls every rules/reference sheet back
    to the ONE layout actually confirmed (the ordinary data-sheet layout: header row 1, data from row
    5) — a stated, known-possibly-wrong fallback, not a verified answer for these sheets. This test
    pins down that fallback behaviour itself, not source-file compatibility."""
    seed(client)
    h = admin()
    day_rates_sheet = [
        ["activity", "weekday", "rate_per_hour"],
        ["Requirement: one row per activity/weekday combination."],
        ["Guidance: rate_per_hour is in units per hour."],
        ["picking", "monday", "999"],   # row 4: example, per the data-sheet fallback layout — ignored
        ["packing", "tuesday", "90"],   # row 5: real data
    ]
    data = _xlsx_bytes({"Day Rates": day_rates_sheet})
    staged = client.post("/v1/imports/xlsx/stage", content=data, headers={**h, "Content-Type": "application/octet-stream"})
    assert staged.status_code == 201, staged.text
    assert staged.json()["applied"][0]["batch"]["ok_rows"] == 1  # only row 5 — rows 2-4 treated as non-data under the fallback layout

    with client.session_local() as s:
        rates = {(d.activity, d.weekday): d.rate_per_hour for d in s.scalars(select(DayRate).where(DayRate.tenant_id == "ten_test"))}
        assert rates == {("packing", "tuesday"): 90.0}  # "picking"/"monday" (row 4) was NOT imported


def test_award_rules_sheet_category_is_rules_reference_but_layout_is_the_fallback(client):
    """Confirms `sheet_category` still correctly identifies Award Rules as a rules/reference sheet
    (distinct from `row_layout`, which is where the fallback is applied) — the categorisation stays
    visible in code even while the layout itself is an acknowledged guess."""
    from app.imports.xlsx import row_layout, sheet_category
    assert sheet_category("award_rules") == "rules_reference"
    assert row_layout("award_rules") == row_layout("workers")  # same fallback layout as an ordinary data sheet, for now

    seed(client)
    h = admin()
    award_sheet = [
        ["award_code", "ordinary_hours_per_day", "overtime_multiplier"],
        ["Requirement: ordinary_hours_per_day must be positive."], [],
        ["example_award", "999", "1.0"],          # row 4: example under the fallback layout — ignored
        ["retail_2024", "8", "1.5"],               # row 5: real data
    ]
    data = _xlsx_bytes({"Award Rules": award_sheet})
    staged = client.post("/v1/imports/xlsx/stage", content=data, headers={**h, "Content-Type": "application/octet-stream"})
    assert staged.status_code == 201, staged.text
    assert staged.json()["applied"][0]["batch"]["ok_rows"] == 1
    with client.session_local() as s:
        assert s.scalar(select(AwardRule).where(AwardRule.tenant_id == "ten_test", AwardRule.award_code == "example_award")) is None
        a = s.scalar(select(AwardRule).where(AwardRule.tenant_id == "ten_test", AwardRule.award_code == "retail_2024"))
        assert a.ordinary_hours_per_day == 8.0 and a.overtime_multiplier == 1.5


# --------------------------------------------------------------------------------------------- v1/v2 version adapters
def test_v1_work_standards_sheet_uses_seconds_per_unit_directly(client):
    seed(client, standards=())
    h = admin()
    data = _xlsx_bytes({"Work Standards": WORK_STANDARDS_SHEET_V1})
    staged = client.post("/v1/imports/xlsx/stage", content=data, headers={**h, "Content-Type": "application/octet-stream"})
    assert staged.status_code == 201, staged.text
    with client.session_local() as s:
        ws = s.scalar(select(WorkStandard).where(WorkStandard.tenant_id == "ten_test", WorkStandard.activity == "packing"))
        assert ws.time_per_unit_seconds == pytest.approx(60, abs=0.01)


def test_v2_work_standards_sheet_converts_standard_rate_per_hour(client):
    """v2's field is a RATE (units/hour), not Tempo's canonical per-unit TIME — converted
    (seconds_per_unit = 3600 / rate), not just relabelled."""
    seed(client, standards=())
    h = admin()
    work_standards_v2 = [
        ["activity", "standard_rate_per_hour"],
        ["Guidance: standard units produced per hour."],
        [],
        ["picking", "999"],       # row 4: example — ignored
        ["packing", "60"],        # row 5: real — 60 units/hour = 60 seconds/unit
    ]
    data = _xlsx_bytes({"Work Standards": work_standards_v2})
    staged = client.post("/v1/imports/xlsx/stage", content=data, headers={**h, "Content-Type": "application/octet-stream"})
    assert staged.status_code == 201, staged.text
    assert staged.json()["applied"][0]["batch"]["ok_rows"] == 1  # row 4's example correctly ignored here too
    with client.session_local() as s:
        ws = s.scalar(select(WorkStandard).where(WorkStandard.tenant_id == "ten_test", WorkStandard.activity == "packing"))
        assert ws.time_per_unit_seconds == pytest.approx(60.0, abs=0.01)  # 3600 / 60 = 60 seconds/unit


def test_v1_skill_code_and_v2_role_both_map_to_workers_skills(client):
    seed(client)
    h = admin()
    v1_workers = [["Employee ID", "Full Name", "Location", "Type", "skill_code"], [], [], [], ["E1", "Worker E1", MEL, "permanent", "forklift"]]
    v2_workers = [["Employee ID", "Full Name", "Location", "Type", "role"], [], [], [], ["E2", "Worker E2", MEL, "permanent", "forklift"]]
    for label, sheet in (("v1", v1_workers), ("v2", v2_workers)):
        data = _xlsx_bytes({"Workers": sheet})
        staged = client.post("/v1/imports/xlsx/stage", content=data, headers={**h, "Content-Type": "application/octet-stream"})
        assert staged.status_code == 201, (label, staged.text)
    with client.session_local() as s:
        from app.models.canonical import SkillCertification
        refs_with_forklift = set()
        for w in s.scalars(select(Worker).where(Worker.tenant_id == "ten_test", Worker.source_system == "tempo_import")):
            if s.scalar(select(SkillCertification.id).where(SkillCertification.tenant_id == "ten_test", SkillCertification.worker_id == w.worker_id, SkillCertification.skill_code == "forklift")):
                refs_with_forklift.add(w.source_ref)
        assert refs_with_forklift == {"E1", "E2"}  # both v1's skill_code and v2's role resolved to the same skill


def test_v1_shift_patterns_sheet_and_v2_shift_templates_both_recognised(client):
    """v1 names the sheet 'Shift Patterns'; v2 splits it into 'Shift Templates' (+ 'Shift Breaks',
    not exercised here). Both must resolve to the same shift_templates entity."""
    seed(client)
    h = admin()
    shift_row = [["site", "shift_code", "start_time", "end_time", "weekdays"], [], [], [], [MEL, "day", "06:00", "14:00", "monday"]]
    for sheet_name in ("Shift Patterns", "Shift Templates"):
        data = _xlsx_bytes({sheet_name: shift_row})
        inspect = client.post("/v1/imports/xlsx/inspect", content=data, headers={**h, "Content-Type": "application/octet-stream"})
        sheets = inspect.json()["sheets"]
        assert sheets[0]["recognised"] is True and sheets[0]["entity"] == "shift_templates", sheet_name
