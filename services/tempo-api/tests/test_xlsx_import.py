"""Version-aware v1/v2 workbook (.xlsx) import, alongside CSV (brief: "retain CSV support without
content-based row deletion"). Built from the brief's literal, stated layout — row 1 is the header,
rows 2-4 are guidance/example content always skipped BY POSITION, and real data begins at row 5 — see
app/imports/xlsx.py's docstring for exactly what this was (and was not) verified against.
"""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook
from sqlalchemy import select

from app.models.canonical import Worker, WorkStandard

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


WORKERS_SHEET = [
    ["Employee ID", "Full Name", "Location", "Type"],          # row 1: header
    ["Fill in your own staff below. Do not delete this row."],  # row 2: guidance (wrong shape entirely — proves position, not shape, decides)
    [],                                                          # row 3: blank
    ["E1042", "Sam Taylor", MEL, "casual"],                      # row 4: the template's own EXAMPLE — a fully well-formed row, structurally ignored
    ["E1", "Worker E1", MEL, "permanent"],                       # row 5: real data
    ["E1042", "Sam Taylor", MEL, "casual"],                      # row 6: real data that happens to match the example EXACTLY — must still be imported
]

WORK_STANDARDS_SHEET = [
    ["activity", "seconds_per_unit"],
    ["Guidance: seconds per unit of work."],
    [],
    ["picking", "45"],   # row 4: example — structurally ignored even though it's a plausible real value
    ["packing", "60"],   # row 5: real data
]


def test_recognised_sheets_are_staged_in_dependency_order_with_row_4_ignored(client):
    seed(client, standards=())  # no pre-seeded work standards — this workbook supplies its own
    h = admin()
    data = _xlsx_bytes({"Workers": WORKERS_SHEET, "Work Standards": WORK_STANDARDS_SHEET, "Notes": [["not a recognised entity"]]})

    inspect = client.post("/v1/imports/csv/inspect".replace("csv", "xlsx"), content=data, headers={**h, "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})
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
    by_entity = {s["entity"]: s for s in body["staged"]}
    # Dependency order preserved: work_standards (no dependency) is staged, and so is workers — in
    # this payload, work_standards appears before workers (processing_rank order), matching the
    # module's explicit dependency ordering rather than the sheets' order in the file.
    ranks = [s["entity"] for s in body["staged"]]
    assert ranks.index("work_standards") < ranks.index("workers")

    ws_batch = by_entity["work_standards"]["batch"]
    assert ws_batch["ok_rows"] == 1  # only "packing" (row 5) — "picking" (row 4) was structurally ignored
    workers_batch = by_entity["workers"]["batch"]
    assert workers_batch["ok_rows"] == 2  # E1 and the example-matching E1042, BOTH real (row 5 and row 6)

    apply1 = client.post(f"/v1/imports/batches/{ws_batch['id']}/apply", headers=h)
    assert apply1.status_code == 200, apply1.text
    apply2 = client.post(f"/v1/imports/batches/{workers_batch['id']}/apply", headers=h)
    assert apply2.status_code == 200, apply2.text

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
    assert staged.json() == {"staged": [], "skipped_sheets": ["Mystery Tab"]}


def test_not_a_real_workbook_is_rejected_cleanly(client):
    h = admin()
    r = client.post("/v1/imports/xlsx/inspect", content=b"this is not an xlsx file", headers={**h, "Content-Type": "application/octet-stream"})
    assert r.status_code == 400
    assert "not a readable" in r.json()["detail"]
