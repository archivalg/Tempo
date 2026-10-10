"""Version-aware (v1/v2) Excel workbook import, alongside Tempo's existing CSV pipeline — not instead
of it (brief: "retain CSV support without content-based row deletion").

Arch's reviewed templates are multi-sheet workbooks where customers are told to upload the WHOLE
file, not one sheet at a time. Per the source-workbook review:

- Ordinary DATA sheets (workers, orders, process steps, ...): row 1 is the header, rows 2-3 are
  metadata, row 4 is an example, and real data begins at row 5. This layout is the only one actually
  confirmed by the review with exact row numbers.
- RULES and REFERENCE sheets (day rates, award rules, fill priorities, headcount limits, unit
  conversions, grade rates, award eligibility restrictions) are KNOWN to use a DIFFERENT layout, but
  NOT a single shared one: the review found each Rules sheet carries its own requirements, guidance
  and instruction/example rows before the actual entries — not a uniform "no metadata, data from row
  2" shape. An earlier version of this module assumed exactly that uniform shape; it was WRONG and has
  been removed. Correct handling needs sheet-specific row numbers this programme has not been given.
  Until a real per-sheet layout is supplied, every rules/reference sheet FALLS BACK to the one layout
  actually confirmed (the ordinary data-sheet layout above) via `_SHEET_SPECIFIC_LAYOUT` — a fallback
  known to likely be wrong for some or all of these sheets, not a verified answer. `sheet_category()`
  still distinguishes the two groups so the fallback (and its honesty) is visible in code, not folded
  silently into "every sheet behaves the same".
- v1 names the activity-rate sheet's own field `seconds_per_unit` (matches Tempo's WorkStandard
  field directly) and the shift sheet "Shift Patterns"; a worker's qualification column is
  `skill_code`.
- v2 instead uses `standard_rate_per_hour` (a rate, not a per-unit time — converted to
  `seconds_per_unit` = 3600 / rate before validation) and splits shifts into "Shift Templates" +
  "Shift Breaks" sheets; a worker's qualification column is `role`.

This was built from the literal, stated review above — it has NOT been tested against the actual
supplied v1/v2 workbook files, which this session has still not been given at any point in this
programme. Source-workbook compatibility is NOT marked confirmed, and must not be read as confirmed
from the fact that tests pass: `tests/test_xlsx_import.py` verifies this module against LOCAL
fixtures built to match the facts stated above, which is fixture-tested import SUPPORT, not source-
file COMPATIBILITY — the two are kept explicitly distinct throughout this module's tests and in
docs/order-driven-planning.md. One further known, stated limitation: if v1's "Shift Patterns" sheet
embeds break definitions inline (rather than as a separate concept the way v2's "Shift Breaks" sheet
is), those inline breaks are NOT extracted — only shift-template-shaped columns (site/shift_code/
start_time/end_time/weekdays) are recognised from that sheet, since the actual column layout of an
inline breaks scheme is not stated and was not guessed.

Each recognised sheet is converted into the exact same (headers, rows) shape `read_csv` produces, then
fed through the SAME staging pipeline (`app.imports.engine.stage`) as any CSV upload — one
`ImportBatch` per sheet. Sheets are staged AND applied together, in dependency order, inside ONE
transaction (see `stage_and_apply_workbook`): a later sheet's cross-reference to an earlier sheet's
rows (e.g. process steps naming a process template from an earlier sheet in the SAME file) resolves
correctly because the earlier sheet's rows are already applied (not just staged) by the time the later
sheet is validated — and if ANY sheet fails, the whole transaction aborts, leaving NO partial import.
"""
from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook

from app.imports.parse import ImportProblem

# The ONE layout actually confirmed by the source-workbook review, with exact row numbers: header
# row 1, metadata rows 2-3, example row 4, data from row 5.
_DATA_SHEET_LAYOUT = {"header_row": 1, "data_start_row": 5}

# Per-ENTITY layout overrides for sheets confirmed to need sheet-specific handling (rules/reference
# sheets — see module docstring). Empty until this programme is given the actual row numbers for each
# specific Rules sheet; every entity not listed here (currently: every entity) falls back to
# `_DATA_SHEET_LAYOUT`, a KNOWN-UNVERIFIED fallback for the rules/reference group, not a confirmed one.
_SHEET_SPECIFIC_LAYOUT: dict[str, dict[str, int]] = {}


def row_layout(entity: str) -> dict[str, int]:
    return _SHEET_SPECIFIC_LAYOUT.get(entity, _DATA_SHEET_LAYOUT)

# Sheet tab name (case/space-insensitive) -> (data_class, entity). Covers every CONTRACTS entry a
# workbook upload could plausibly carry; v1/v2 naming variants stated in the source-workbook review
# are included explicitly (Shift Patterns / Shift Templates / Shift Breaks).
_SHEET_ALIASES: dict[str, tuple[str, str]] = {
    "sites": ("master", "sites"), "warehouses": ("master", "sites"),
    "customers": ("master", "customers"),
    "zones": ("master", "zones"), "areas": ("master", "zones"),
    "work standards": ("master", "work_standards"), "work_standards": ("master", "work_standards"), "activities": ("master", "work_standards"), "activity standards": ("master", "work_standards"),
    "workers": ("master", "workers"), "staff": ("master", "workers"), "employees": ("master", "workers"),
    "rates": ("master", "rates"), "pay rates": ("master", "rates"), "labour rates": ("master", "rates"),
    "availability": ("master", "availability"), "leave": ("master", "availability"),
    "weekly availability": ("master", "weekly_availability"),
    "operating calendar": ("master", "operating_calendar"), "operating hours": ("master", "operating_calendar"),
    "shift templates": ("master", "shift_templates"), "shifts": ("master", "shift_templates"), "shift patterns": ("master", "shift_templates"),  # v1 (Shift Patterns) vs v2 (Shift Templates)
    "shift breaks": ("master", "shift_breaks"), "breaks": ("master", "shift_breaks"),  # v2 only — v1's Shift Patterns has no separate breaks sheet (see module docstring)
    "equipment": ("master", "equipment"),
    "activity roles": ("master", "activity_roles"),
    "process templates": ("master", "process_templates"), "processes": ("master", "process_templates"),
    "process steps": ("master", "process_steps"), "tasks": ("master", "process_steps"),
    "orders": ("master", "orders"), "outbound orders": ("master", "orders"),
    "worker activity rates": ("master", "worker_activity_rates"), "task rates": ("master", "worker_activity_rates"), "individual rates": ("master", "worker_activity_rates"),
    "unit conversions": ("master", "unit_conversions"),
    "fill priorities": ("master", "fill_priorities"),
    "absenteeism": ("master", "absenteeism"),
    "headcount limits": ("master", "headcount_limits"),
    "grade rates": ("master", "grade_rates"),
    "productivity loss": ("master", "productivity_loss"),
    "staging capacity": ("master", "staging_capacity"),
    "staging movements": ("master", "staging_movements"),
    "indirect headcount": ("master", "indirect_headcount"), "supervision": ("master", "indirect_headcount"),
    "day rates": ("master", "day_rates"),
    "award rules": ("master", "award_rules"), "awards": ("master", "award_rules"),
    "award eligibility restrictions": ("master", "award_eligibility_restrictions"),
}

# Rules/reference sheets are KNOWN to need sheet-specific layouts this programme has not been given
# (see module docstring) — kept as its own category so that fact stays visible in code, even though
# `row_layout()` currently falls every one of them back to the same `_DATA_SHEET_LAYOUT` as "data"
# sheets. Keyed by entity, not sheet name, since the alias table above already folds several sheet-
# name spellings onto one entity.
_RULES_REFERENCE_ENTITIES = {"day_rates", "award_rules", "award_eligibility_restrictions", "fill_priorities",
                             "headcount_limits", "unit_conversions", "grade_rates"}


def sheet_category(entity: str) -> str:
    return "rules_reference" if entity in _RULES_REFERENCE_ENTITIES else "data"


# v1/v2 field-name adapters, keyed by entity: canonical field name -> set of version-specific header
# spellings to also recognise, beyond the field's own CSV synonyms (contracts.py). "seconds_per_unit"
# needs no adapter — it already IS the v1 (and canonical) name. "standard_rate_per_hour" (v2) requires
# a VALUE transform, not just a header rename, so it's handled separately in `_adapt_work_standards`.
_FIELD_ALIASES: dict[str, dict[str, tuple[str, ...]]] = {
    "workers": {"skills": ("skill_code", "role")},  # v1: skill_code, v2: role — both treated as the worker's one qualification value
}
_V2_RATE_HEADER = "standard_rate_per_hour"

# Dependency order for staging multiple sheets from ONE workbook in a single pass — NOT the same as
# contracts.DATA_CLASSES's tuple, which is grouped for display, not safe processing order (e.g. it
# lists "workers" before "sites", but a worker's home_site must already exist). A sheet not in this
# list (there should be none) sorts after everything named here, in whatever order it was found.
_PROCESSING_ORDER: tuple[str, ...] = (
    "sites", "customers", "zones", "work_standards", "workers", "rates", "availability", "weekly_availability",
    "operating_calendar", "shift_templates", "shift_breaks", "equipment", "activity_roles",
    "process_templates", "process_steps", "orders", "worker_activity_rates", "unit_conversions",
    "fill_priorities", "absenteeism", "headcount_limits", "grade_rates", "productivity_loss",
    "staging_capacity", "staging_movements", "indirect_headcount", "day_rates", "award_rules", "award_eligibility_restrictions",
)


def sheet_entity(sheet_name: str) -> tuple[str, str] | None:
    """The (data_class, entity) a sheet tab name maps to, or None if unrecognised — an unrecognised
    sheet is reported back to the caller, never silently dropped (see xlsx_stage/xlsx_inspect)."""
    return _SHEET_ALIASES.get(sheet_name.strip().lower())


def processing_rank(entity: str) -> int:
    return _PROCESSING_ORDER.index(entity) if entity in _PROCESSING_ORDER else len(_PROCESSING_ORDER)


def _cell_to_str(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _adapt_work_standards(headers: list[str], rows: list[dict[str, str]]) -> None:
    """v2's `standard_rate_per_hour` is a RATE, not Tempo's canonical per-unit time — a VALUE
    transform (3600 / rate), not just a header rename, so it can't be handled by header synonyms
    alone. Mutates both `headers` (so `suggest_mapping` can find the new column) and `rows` in place,
    adding a `seconds_per_unit` header/key; v1 sheets (which already use `seconds_per_unit` directly)
    are untouched."""
    norm_headers = {h.strip().lower().replace(" ", "_") for h in headers}
    if "seconds_per_unit" in norm_headers or _V2_RATE_HEADER not in norm_headers:
        return
    rate_header = next(h for h in headers if h.strip().lower().replace(" ", "_") == _V2_RATE_HEADER)
    headers.append("seconds_per_unit")
    for r in rows:
        raw = r.get(rate_header, "")
        try:
            rate = float(raw)
        except ValueError:
            continue
        if rate > 0:
            r["seconds_per_unit"] = str(round(3600 / rate, 4))


def _apply_field_aliases(entity: str, headers: list[str]) -> list[str]:
    """Renames a v1/v2-specific header (e.g. `skill_code` or `role`) to Tempo's canonical field name
    (`skills`) so the ordinary header-synonym mapping (`app.imports.parse.suggest_mapping`) finds it —
    column HEADER renames only; a VALUE transform (like the rate conversion above) needs its own
    function since renaming alone can't convert units."""
    aliases = _FIELD_ALIASES.get(entity, {})
    rename = {alt: canonical for canonical, alts in aliases.items() for alt in alts}
    norm = lambda h: h.strip().lower().replace(" ", "_")  # noqa: E731
    return [rename.get(norm(h), h) for h in headers]


def read_xlsx(data: bytes) -> dict[str, tuple[list[str], list[dict[str, str]]]]:
    """Every sheet in the workbook, each as (headers, rows) — the same shape `read_csv` returns, so
    every downstream caller (mapping suggestion, `engine.stage`) is unchanged. An ordinary data sheet
    has its header on row 1 and data from row 5 (rows 2-4 are metadata/example, skipped by position);
    a rules/reference sheet (`sheet_category`) has data from row 2. A genuinely blank data row (every
    cell empty) is skipped the same way `read_csv` skips one. v1/v2 field-name differences are
    resolved here too (see module docstring) before the row dicts are returned."""
    try:
        wb = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises several distinct exception types for a bad file
        raise ImportProblem("the file is not a readable .xlsx workbook") from exc
    sheets: dict[str, tuple[list[str], list[dict[str, str]]]] = {}
    for ws in wb.worksheets:
        mapped = sheet_entity(ws.title)
        data_start_row = row_layout(mapped[1])["data_start_row"] if mapped else _DATA_SHEET_LAYOUT["data_start_row"]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_cells = next(rows_iter)
        except StopIteration:
            sheets[ws.title] = ([], [])
            continue
        headers = [_cell_to_str(h) for h in header_cells]
        if mapped:
            headers = _apply_field_aliases(mapped[1], headers)
        rows: list[dict[str, str]] = []
        for row_no, cells in enumerate(rows_iter, start=2):
            if row_no < data_start_row:
                continue  # metadata/example rows (data sheets only) — skipped by position, never by content
            values = [_cell_to_str(c) for c in cells]
            if not any(values):
                continue  # a genuinely blank data row — same convention as read_csv
            rows.append({h: (values[i] if i < len(values) else "") for i, h in enumerate(headers) if h})
        if mapped and mapped[1] == "work_standards":
            _adapt_work_standards(headers, rows)
        sheets[ws.title] = (headers, rows)
    wb.close()
    return sheets
