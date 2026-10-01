"""CSV export of the report read models.

Exports reuse the same read models as the screens, so a file can never show a figure the screen would hide
(rates need labour.rates.read, names need labour.worker_names). Every cell is neutralised against spreadsheet
formula injection, and every export is audited with the row count.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(v: Any) -> str:
    """Strings that a spreadsheet would run as a formula are prefixed with an apostrophe; numbers pass through."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    return "'" + s if s.startswith(_FORMULA) else s


def _local(v: datetime | None, tz: ZoneInfo) -> str:
    return v.astimezone(tz).strftime("%Y-%m-%d %H:%M") if v else ""


def to_csv(header: list[str], rows: Iterable[list[Any]], preamble: list[str]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    for line in preamble:
        w.writerow([safe_cell("# " + line)])
    w.writerow(header)
    for r in rows:
        w.writerow([safe_cell(c) for c in r])
    return buf.getvalue()


def _pre(kind: str, data: dict, now: datetime) -> list[str]:
    r, s = data["range"], data["site"]
    return [f"Tempo {kind} export — {s['name']} ({s['timezone']})", f"Week from {r['start']} for {r['days']} day(s); generated {now.strftime('%Y-%m-%d %H:%M UTC')}"]


def variance_csv(data: dict, now: datetime) -> tuple[str, int]:
    rates = "planned_cost" in data["totals"]
    head = ["date", "status", "scheduled_hours", "attended_hours_ESTIMATE", "payable_hours_CONFIRMED", "variance_hours", "adherence_pct", "late", "no_shows",
            "overtime_hours", "forecast_units", "actual_units", "forecast_error_pct"] + (["planned_cost", "estimated_actual_cost_ESTIMATE", "confirmed_cost"] if rates else [])
    rows = []
    for d in data["days"]:
        nd = d["status"] == "upcoming"  # nothing has happened yet: blank, never zero
        v = lambda k: None if nd else d.get(k)  # noqa: E731
        row = [d["date"], d["status"], v("scheduled_hours"), v("attended_hours"), v("payable_hours"), v("variance_hours"), d.get("adherence_pct"), d.get("late"), d.get("no_shows"),
               v("overtime_hours"), d.get("forecast_units"), d.get("actual_units"), d.get("forecast_ape_pct")]
        if rates:
            row += [v("planned_cost"), v("estimated_actual_cost"), v("confirmed_cost")]
        rows.append(row)
    pre = _pre("variance", data, now) + ["Attended hours and estimated cost are ESTIMATES until timesheets are approved; payable hours and confirmed cost are CONFIRMED."]
    return to_csv(head, rows, pre), len(rows)


def timesheets_csv(data: dict, now: datetime) -> tuple[str, int]:
    tz = ZoneInfo(data["site"]["timezone"])
    head = ["worker", "role", "clock_in", "clock_out", "state", "scheduled_start", "scheduled_end", "rostered", "punched_hours", "scheduled_hours", "payable_hours_CONFIRMED", "correction"]
    rows = [[s["worker_label"], s["role"], _local(s["clock_in"], tz), _local(s["clock_out"], tz) if s["clock_out"] else "open", s["approval"], _local(s["scheduled_start"], tz),
             _local(s["scheduled_end"], tz), s["matched"], s["punched_hours"], s["scheduled_hours"], s["payable_hours"],
             (s["adjustment"]["state"] if s["adjustment"] else "")] for s in data["sessions"]]
    return to_csv(head, rows, _pre("timesheets", data, now) + ["Times are site-local. Original punches are never edited; a correction is shown in its own column."]), len(rows)


def demand_csv(data: dict, now: datetime) -> tuple[str, int]:
    head = ["date", "activity", "actual_units", "forecast_units", "forecast_lower", "forecast_upper", "seconds_per_unit", "required_hours"]
    rows = [[r["date"], r["activity"], r["actual_units"], r["forecast_units"], r["forecast_lower"], r["forecast_upper"], r["seconds_per_unit"], r["required_hours"]] for r in data["rows"]]
    return to_csv(head, rows, _pre("demand", data, now)), len(rows)
