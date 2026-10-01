"""Versioned data contracts for the four data classes (roadmap M1). One definition drives the CSV template, the API reference,
the column mapping and the validators, so they cannot drift apart. Breaking changes need a new CONTRACT_VERSION."""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

CONTRACT_VERSION = "1.0"
MAX_ROWS = 20_000          # synchronous limit; larger files must be split (a background worker does not exist yet)
MAX_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Field:
    name: str
    kind: str                       # text | enum | number | int | datetime | date | list
    required: bool
    description: str
    example: str
    choices: tuple[str, ...] = ()
    synonyms: tuple[str, ...] = ()  # header names we recognise automatically


@dataclass(frozen=True)
class Contract:
    data_class: str
    entity: str | None
    title: str
    purpose: str
    key: tuple[str, ...]
    fields: tuple[Field, ...]
    batch_options: tuple[Field, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def names(self) -> list[str]:
        return [f.name for f in self.fields]


SITE = Field("site", "text", True, "Site ID as shown in Tempo.", "mel_dc_01", synonyms=("site_id", "location", "warehouse", "dc"))
ACTIVITY = Field("activity", "text", True, "Activity name; must already have a work standard.", "picking", synonyms=("task", "work_type", "function"))
GRAIN = Field("grain", "enum", True, "Length of the period.", "day", ("hour", "day"), ("period", "granularity"))
PERIOD_START = Field("period_start", "datetime", True, "Start of the period. ISO 8601 with offset (2026-10-05T00:00:00+11:00) or site-local time (2026-10-05 00:00). Hours start on the hour; days at local midnight.", "2026-10-05",
                     synonyms=("start", "date", "period", "from", "datetime"))

CONTRACTS: dict[tuple[str, str | None], Contract] = {(c.data_class, c.entity): c for c in (
    Contract("master", "workers", "Staff (master data)", "Create or update workers. Re-uploading the same file changes nothing.", ("worker_ref",), (
        Field("worker_ref", "text", True, "Your stable ID for the person (payroll or HR number). Never reused for someone else.", "E1042", synonyms=("employee_id", "staff_id", "id", "worker_id", "emp_no")),
        Field("name", "text", True, "Full name. Treated as personal information.", "Sam Taylor", synonyms=("full_name", "employee_name", "worker_name")),
        SITE,
        Field("employment_type", "enum", True, "How the person is engaged.", "casual", ("permanent", "casual", "labour_hire"), ("type", "employment", "contract_type")),
        Field("status", "enum", False, "Defaults to active. Use inactive for people who have left (history is kept).", "active", ("active", "inactive"), ("active_flag",)),
        Field("skills", "list", False, "Skills or certifications, separated by semicolons. Listed skills are added; none are removed.", "picker;forklift", synonyms=("roles", "certifications", "licences")),
        Field("employee_no", "text", False, "Payroll number if different from worker_ref.", "104233", synonyms=("payroll_no", "payroll_number")),
    ), notes=("Rows are matched on worker_ref, so the same person is updated, not duplicated.",)),
    Contract("master", "work_standards", "Work standards (master data)", "Seconds of labour per unit of work, per activity. Needed before forecasts and actuals can name an activity.", ("activity",), (
        ACTIVITY,
        Field("seconds_per_unit", "number", True, "Standard labour seconds for one unit.", "45", synonyms=("seconds", "sec_per_unit", "time_per_unit", "standard")),
        Field("effective_from", "date", False, "Date the standard starts (defaults to today).", "2026-10-01", synonyms=("start_date", "from")),
    ), notes=("A changed value closes the previous standard on the day the new one starts.",)),
    Contract("forecast", None, "Forecast workload", "Expected units per activity and period. Customer-supplied forecasts are versioned and shown with their origin.", ("site", "activity", "period_start", "grain"), (
        SITE, ACTIVITY, PERIOD_START, GRAIN,
        Field("units", "number", True, "Expected units in the period.", "26500", synonyms=("forecast", "volume", "quantity", "expected")),
        Field("lower", "number", False, "Optional low estimate.", "24000", synonyms=("low", "min")),
        Field("upper", "number", False, "Optional high estimate.", "29000", synonyms=("high", "max")),
    ), batch_options=(
        Field("forecast_version", "text", True, "A label for this forecast (for example 2026-10-W2-v1). A label can be used once.", "2026-10-W2-v1"),
        Field("generated_at", "datetime", False, "When the customer produced the forecast.", "2026-10-01T06:00:00+11:00"),
    ), notes=("A revised forecast flags draft rosters for review. It never rewrites a published roster.",)),
    Contract("transactions", None, "Workload events (actuals, one row per event)", "Individual operational events: what was processed, when.", ("source", "event_id"), (
        Field("event_id", "text", True, "Your unique ID for the event. Resending the same event changes nothing.", "RCV-88231", synonyms=("id", "transaction_id", "txn_id", "reference")),
        SITE, ACTIVITY,
        Field("occurred_at", "datetime", True, "When it happened. ISO 8601 with offset, or site-local time.", "2026-09-28 14:32", synonyms=("timestamp", "time", "event_time", "datetime")),
        Field("quantity", "number", True, "Units processed (not negative).", "12", synonyms=("units", "qty", "volume")),
        Field("unit", "text", False, "Unit label (defaults to units). All rows for an activity must use one unit.", "units", synonyms=("uom",)),
        Field("customer", "text", False, "Customer ID if you track workload per customer.", "cust_A", synonyms=("customer_id",)),
        Field("action", "enum", False, "create (default), correct or cancel.", "create", ("create", "correct", "cancel")),
        Field("revision", "int", False, "Increasing number for corrections. A lower revision than the one held is ignored as out of date.", "2"),
        Field("source", "text", False, "Name of the sending system (defaults to default). Event IDs are unique per source.", "wms", synonyms=("system",)),
    ), notes=("Events feed hourly workload actuals. If bulk totals are authoritative for the same site and activity, events are stored but not counted.",)),
    Contract("bulk", None, "Workload totals (actuals, per period)", "Hourly or daily totals when individual events are not available.", ("site", "activity", "period_start", "grain"), (
        SITE, ACTIVITY, PERIOD_START, GRAIN,
        Field("units", "number", True, "Total units processed in the period (not negative).", "26140", synonyms=("quantity", "volume", "total", "actual")),
        Field("customer", "text", False, "Customer ID if you track workload per customer.", "cust_A", synonyms=("customer_id",)),
    ), batch_options=(
        Field("mode", "enum", True, "upsert: add or update these periods only. replace_slice: replace everything in the stated date range for the activities in the file.", "upsert", ("upsert", "replace_slice")),
        Field("slice_start", "date", False, "First local date of the slice (required for replace_slice).", "2026-10-01"),
        Field("slice_end", "date", False, "Last local date of the slice, inclusive (required for replace_slice).", "2026-10-07"),
        Field("control_total", "number", False, "Optional total of units you expect; the import is held if the file does not add up to it.", "180000"),
        Field("take_over", "bool", False, "Allow this upload to replace workload that came from a different source for the same periods.", "false"),
    ), notes=("Replacing a slice needs its range stated; an ambiguous replacement is refused.",)),
)}

DATA_CLASSES = {"master": ("workers", "work_standards"), "forecast": (None,), "transactions": (None,), "bulk": (None,)}


def contract_for(data_class: str, entity: str | None) -> Contract:
    c = CONTRACTS.get((data_class, entity if data_class == "master" else None))
    if c is None:
        raise KeyError(f"unknown data class '{data_class}'" + (f" / '{entity}'" if entity else ""))
    return c


def describe(c: Contract) -> dict:
    f = lambda x: {"name": x.name, "type": x.kind, "required": x.required, "description": x.description, "example": x.example, **({"choices": list(x.choices)} if x.choices else {})}  # noqa: E731
    return {"data_class": c.data_class, "entity": c.entity, "title": c.title, "purpose": c.purpose, "contract_version": CONTRACT_VERSION, "key": list(c.key),
            "fields": [f(x) for x in c.fields], "batch_options": [f(x) for x in c.batch_options], "notes": list(c.notes), "limits": {"max_rows_per_batch": MAX_ROWS, "max_file_bytes": MAX_BYTES}}


def template_csv(c: Contract) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(c.names)
    w.writerow([x.example for x in c.fields])
    return buf.getvalue()
