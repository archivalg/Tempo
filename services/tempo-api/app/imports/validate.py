"""Row validation for every data class. Pure functions of (row, context): no writes happen here.

A row is normalised into plain JSON (so exactly what was validated is what is applied) or rejected with plain-language messages.
Unknown references are reported without confirming whether another organisation uses the same ID."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.imports.contracts import Contract
from app.imports.parse import ImportProblem, aligned_bucket, parse_local_date, parse_moment
from app.models.scheduling import WEEKDAYS
from app.solvers.shifts import hhmm_to_minutes, shift_elapsed_minutes


@dataclass
class Lookups:
    """Everything a row may legitimately refer to, already limited to the caller's tenant and granted sites."""
    sites: dict[str, ZoneInfo]                    # site_id → timezone, only sites the caller may use
    activities: set[str]                          # activities that have a work standard
    customers: set[str]
    workers_by_ref: dict[str, str] = field(default_factory=dict)  # source_ref → worker_id (existing, for "update" vs "create")
    existing_sites: dict[str, str] = field(default_factory=dict)  # every site of the tenant → its time zone name (to refuse timezone changes)
    worker_site: dict[str, str] = field(default_factory=dict)     # source_ref → home site of that worker
    activity_units: dict[tuple[str, str], str] = field(default_factory=dict)  # (site, activity) → unit already used
    zone_ids: set[tuple[str, str]] = field(default_factory=set)               # (site, zone_id) that already exist
    operating_calendar: dict[tuple[str, str], dict] = field(default_factory=dict)  # (site, weekday) → {is_24h, is_closed, open_time, close_time}
    shift_templates: dict[tuple[str, str], dict] = field(default_factory=dict)     # (site, shift_code) → {elapsed_minutes} for active templates
    process_templates: set[tuple[str, str]] = field(default_factory=set)          # (site, process_code) that already exist
    labour_providers: set[str] = field(default_factory=set)                       # provider_id that already exist
    staging_units: dict[tuple[str, str], str] = field(default_factory=dict)       # (site, zone) → capacity unit
    equipment_ids: set[tuple[str, str]] = field(default_factory=set)              # (site, equipment_id) that already exist


def _msg(level: str, field_: str, code: str, text: str) -> dict:
    return {"level": level, "field": field_, "code": code, "text": text}


def _num(v: str, name: str, *, minimum: float | None = 0.0, maximum: float = 1e9) -> float:
    try:
        x = float(v.replace(",", "")) if isinstance(v, str) else float(v)
    except (ValueError, AttributeError):
        raise ImportProblem(f"{name} must be a number (got '{v}')") from None
    if not math.isfinite(x):
        raise ImportProblem(f"{name} must be a finite number")
    if minimum is not None and x < minimum:
        raise ImportProblem(f"{name} cannot be below {minimum:g} (got {x:g})")
    if x > maximum:
        raise ImportProblem(f"{name} is implausibly large ({x:g}); check the units")
    return x


def _site(v: str, lk: Lookups) -> tuple[str, ZoneInfo]:
    s = v.strip()
    if not s:
        raise ImportProblem("site is required")
    if s not in lk.sites:
        raise ImportProblem(f"site '{s}' is not one of your sites. Use the Site ID shown in Tempo.")
    return s, lk.sites[s]


def _activity(v: str, lk: Lookups) -> str:
    """Matched case-insensitively against Work standards, the same way `unit` is normalised
    elsewhere — a customer's own sheets routinely differ only in case ("Picking" vs "picking"), and
    that must not be treated as two different activities or as a spelling error to fix."""
    a = v.strip().lower()
    if not a:
        raise ImportProblem("activity is required")
    if a not in lk.activities:
        raise ImportProblem(f"activity '{v.strip()}' has no work standard. Add it under Work standards first (or correct the spelling).")
    return a


def _customer(v: str, lk: Lookups) -> str | None:
    c = v.strip()
    if not c:
        return None
    if c not in lk.customers:
        raise ImportProblem(f"customer '{c}' is not set up in Tempo")
    return c


def _required(row: dict, contract: Contract, errs: list[dict]) -> None:
    for f in contract.fields:
        if f.required and not str(row.get(f.name, "")).strip():
            errs.append(_msg("error", f.name, "required", f"{f.name} is required"))


def validate_row(contract: Contract, row: dict, lk: Lookups) -> tuple[dict | None, list[dict]]:
    msgs: list[dict] = []
    _required(row, contract, msgs)
    out: dict = {}
    fn = _VALIDATORS[(contract.data_class, contract.entity)]
    # validate each field independently so one bad cell does not hide the others
    for name, check in fn(row, lk):
        try:
            out.update(check())
        except ImportProblem as e:
            if not any(m["field"] == name and m["code"] == "required" for m in msgs):
                msgs.append(_msg("error", name, "invalid", str(e)))
    if contract.entity == "availability" and "start_at" in out and "end_at" in out:
        a, b = datetime.fromisoformat(out["start_at"]), datetime.fromisoformat(out["end_at"])
        if b <= a:
            msgs.append(_msg("error", "to", "invalid", "to must be after from"))
        elif (b - a).days > 60:
            msgs.append(_msg("error", "to", "invalid", "an entry can cover at most 60 days; split longer leave into several rows"))
    elif contract.entity == "shift_templates" and all(k in out for k in ("site", "start_time", "end_time", "weekdays")):
        for wd in out["weekdays"]:
            cal = lk.operating_calendar.get((out["site"], wd))
            if cal is None:
                continue
            if cal["is_closed"]:
                msgs.append(_msg("warning", "weekdays", "operating_calendar", f"{wd}: the operating calendar marks this site closed, but the shift is scheduled to run — not changed automatically"))
            elif not cal["is_24h"] and cal["open_time"] and cal["close_time"]:
                s_min, e_min = hhmm_to_minutes(out["start_time"]), hhmm_to_minutes(out["end_time"])
                o_min, c_min = hhmm_to_minutes(cal["open_time"]), hhmm_to_minutes(cal["close_time"])
                if e_min > s_min and (s_min < o_min or e_min > c_min):  # only checked for same-day shifts; overnight spans are a Stage 2+ cross-midnight calendar question
                    msgs.append(_msg("warning", "weekdays", "operating_calendar", f"{wd}: shift {out['start_time']}-{out['end_time']} falls outside operating hours {cal['open_time']}-{cal['close_time']} — not changed automatically"))
    elif contract.entity == "shift_breaks" and all(k in out for k in ("site", "shift_code", "starts_after_minutes", "duration_minutes")):
        tmpl = lk.shift_templates.get((out["site"], out["shift_code"]))
        if tmpl is not None and out["starts_after_minutes"] + out["duration_minutes"] > tmpl["elapsed_minutes"]:
            msgs.append(_msg("error", "duration_minutes", "invalid", f"break does not fit inside the {tmpl['elapsed_minutes']}-minute shift"))
    elif contract.entity == "headcount_limits" and "min_headcount" in out and "max_headcount" in out:
        if out["min_headcount"] > out["max_headcount"]:
            msgs.append(_msg("error", "min_headcount", "invalid", f"min_headcount ({out['min_headcount']}) exceeds max_headcount ({out['max_headcount']})"))
    elif contract.entity == "weekly_availability" and "available" in out and "earliest_start" in out:
        if not out["available"] and out["earliest_start"] is not None:
            msgs.append(_msg("error", "earliest_start", "invalid", "earliest_start/latest_finish must be blank when available is false"))
    elif contract.entity == "productivity_loss" and "type" in out and "percent_loss" in out and "off_task_hours" in out:
        has_pct, has_hrs = out["percent_loss"] is not None, out["off_task_hours"] is not None
        if out["type"] == "congestion" and (not has_pct or has_hrs):
            msgs.append(_msg("error", "percent_loss", "invalid", "type congestion needs percent_loss and no off_task_hours"))
        elif out["type"] == "off_task" and (not has_hrs or has_pct):
            msgs.append(_msg("error", "off_task_hours", "invalid", "type off_task needs off_task_hours and no percent_loss"))
    if any(m["level"] == "error" for m in msgs):
        return None, msgs
    return out, msgs


def _g(row: dict, k: str) -> str:
    v = row.get(k, "")
    return "" if v is None else str(v).strip()


def _workers(row, lk):
    yield "worker_ref", lambda: {"worker_ref": _need(_g(row, "worker_ref"), "worker_ref")}
    yield "name", lambda: {"name": _need(_g(row, "name"), "name")[:200]}
    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "employment_type", lambda: {"employment_type": _enum(_g(row, "employment_type").lower().replace(" ", "_").replace("-", "_"), ("permanent", "casual", "labour_hire"), "employment_type", {"full_time": "permanent", "part_time": "permanent", "contractor": "labour_hire", "agency": "labour_hire", "temp": "casual"})}
    yield "status", lambda: {"status": _enum(_g(row, "status").lower() or "active", ("active", "inactive"), "status", {"yes": "active", "true": "active", "no": "inactive", "false": "inactive", "terminated": "inactive"})}
    yield "skills", lambda: {"skills": sorted({s.strip().lower() for s in _g(row, "skills").replace(",", ";").split(";") if s.strip()})}
    yield "employee_no", lambda: {"employee_no": _g(row, "employee_no") or None}
    yield "position_grade", lambda: {"position_grade": _g(row, "position_grade")[:80] or None}
    yield "award", lambda: {"award": _g(row, "award")[:80] or None}


def _sites(row, lk):
    def tz():
        name = _need(_g(row, "timezone"), "timezone")
        try:
            ZoneInfo(name)
        except Exception:  # noqa: BLE001
            raise ImportProblem(f"'{name}' is not a time zone name. Use a name like Australia/Melbourne.") from None
        sid = _g(row, "site_id")
        if sid in lk.existing_sites and lk.existing_sites[sid] != name:
            raise ImportProblem(f"site '{sid}' already uses {lk.existing_sites[sid]}; a site's time zone cannot be changed by upload because it would move its history")
        return {"timezone": name}

    def sid():
        v = _need(_g(row, "site_id"), "site_id")
        if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,40}", v):
            raise ImportProblem("site_id may use letters, numbers, underscore and hyphen only (up to 40)")
        return {"site_id": v}

    yield "site_id", sid
    yield "name", lambda: {"name": _need(_g(row, "name"), "name")[:200]}
    yield "timezone", tz
    yield "operating_mode", lambda: {"operating_mode": _enum(_g(row, "operating_mode").lower() or "standalone", ("standalone", "overlay"), "operating_mode")}


def _customers(row, lk):
    yield "customer_id", lambda: {"customer_id": _need(_g(row, "customer_id"), "customer_id")[:80]}
    yield "name", lambda: {"name": _need(_g(row, "name"), "name")[:200]}
    yield "status", lambda: {"status": _enum(_g(row, "status").lower() or "active", ("active", "inactive"), "status")}


def _availability(row, lk):
    state: dict = {}

    def ref():
        r = _need(_g(row, "worker_ref"), "worker_ref")
        if r not in lk.worker_site:
            raise ImportProblem(f"worker_ref '{r}' is not a person from your staff upload. Upload staff first.")
        state["tz"] = lk.sites.get(lk.worker_site[r])
        if state["tz"] is None:
            raise ImportProblem("that person's site is not one you may use")
        return {"worker_ref": r}

    def when(name):
        def f():
            if "tz" not in state:
                raise ImportProblem(f"cannot read {name} until worker_ref is valid")
            return {("start_at" if name == "from" else "end_at"): parse_moment(_g(row, name), state["tz"]).isoformat()}
        return f

    yield "worker_ref", ref
    yield "kind", lambda: {"kind": _enum(_g(row, "kind").lower().replace(" ", "_"), ("unavailable", "leave", "rdo"), "kind", {"annual_leave": "leave", "holiday": "leave", "day_off": "rdo", "rostered_day_off": "rdo", "unavail": "unavailable"})}
    yield "from", when("from")
    yield "to", when("to")


def _rates(row, lk):
    yield "employment_type", lambda: {"employment_type": _enum(_g(row, "employment_type").lower().replace(" ", "_").replace("-", "_"), ("permanent", "casual", "labour_hire"), "employment_type", {"full_time": "permanent", "part_time": "permanent", "contractor": "labour_hire", "agency": "labour_hire", "temp": "casual"})}
    yield "role", lambda: {"role": (_g(row, "role").lower() or "general")[:80]}
    yield "hourly_rate", lambda: {"hourly_rate": _num(_g(row, "hourly_rate"), "hourly_rate", minimum=0.01, maximum=10000)}
    yield "overtime_multiplier", lambda: {"overtime_multiplier": _num(_g(row, "overtime_multiplier"), "overtime_multiplier", minimum=1.0, maximum=5.0) if _g(row, "overtime_multiplier") else None}
    yield "surcharge", lambda: {"surcharge": _num(_g(row, "surcharge"), "surcharge", minimum=0.0, maximum=10000) if _g(row, "surcharge") else None}


def _standards(row, lk):
    yield "activity", lambda: {"activity": _need(_g(row, "activity"), "activity").lower()[:80]}
    yield "seconds_per_unit", lambda: {"seconds_per_unit": _num(_g(row, "seconds_per_unit"), "seconds_per_unit", minimum=0.1, maximum=86400)}
    yield "effective_from", lambda: {"effective_from": (parse_local_date(_g(row, "effective_from")) if _g(row, "effective_from") else datetime.now(timezone.utc).date()).isoformat()}
    yield "function", lambda: {"function": _g(row, "function")[:80] or None}
    yield "flow", lambda: {"flow": _g(row, "flow")[:80] or None}
    yield "required_skill", lambda: {"required_skill": _g(row, "required_skill")[:80] or None}


def _forecast(row, lk):
    state: dict = {}

    def site():
        s, tz = _site(_g(row, "site"), lk)
        state["tz"] = tz
        return {"site": s}

    def period():
        if "tz" not in state:
            raise ImportProblem("cannot read the period until the site is valid")
        start, minutes = aligned_bucket(_g(row, "period_start"), _g(row, "grain").lower(), state["tz"])
        return {"bucket_start": start.isoformat(), "bucket_minutes": minutes}

    yield "site", site
    yield "activity", lambda: {"activity": _activity(_g(row, "activity"), lk)}
    yield "grain", lambda: {"grain": _enum(_g(row, "grain").lower(), ("hour", "day"), "grain", {"hourly": "hour", "daily": "day"})}
    yield "period_start", period
    yield "units", lambda: {"units": _num(_g(row, "units"), "units")}

    def band():
        lo = _num(_g(row, "lower"), "lower") if _g(row, "lower") else None
        hi = _num(_g(row, "upper"), "upper") if _g(row, "upper") else None
        u = _num(_g(row, "units"), "units")
        if lo is not None and lo > u or hi is not None and hi < u or lo is not None and hi is not None and lo > hi:
            raise ImportProblem("lower must not exceed units, and upper must not be below units")
        return {"lower": lo, "upper": hi}

    yield "lower", band


def _bulk(row, lk):
    state: dict = {}

    def site():
        s, tz = _site(_g(row, "site"), lk)
        state["tz"] = tz
        return {"site": s}

    def period():
        if "tz" not in state:
            raise ImportProblem("cannot read the period until the site is valid")
        start, minutes = aligned_bucket(_g(row, "period_start"), _g(row, "grain").lower(), state["tz"])
        return {"bucket_start": start.isoformat(), "bucket_minutes": minutes}

    yield "site", site
    yield "activity", lambda: {"activity": _activity(_g(row, "activity"), lk)}
    yield "grain", lambda: {"grain": _enum(_g(row, "grain").lower(), ("hour", "day"), "grain", {"hourly": "hour", "daily": "day"})}
    yield "period_start", period
    yield "units", lambda: {"units": _num(_g(row, "units"), "units")}
    yield "customer", lambda: {"customer": _customer(_g(row, "customer"), lk)}


def _transactions(row, lk):
    state: dict = {}

    def site():
        s, tz = _site(_g(row, "site"), lk)
        state["tz"] = tz
        return {"site": s}

    def when():
        if "tz" not in state:
            raise ImportProblem("cannot read the time until the site is valid")
        t = parse_moment(_g(row, "occurred_at"), state["tz"])
        if t > datetime.now(timezone.utc).replace(microsecond=0) + __import__("datetime").timedelta(days=1):
            raise ImportProblem("occurred_at is in the future")
        if t.year < 2000:
            raise ImportProblem("occurred_at is before the year 2000")
        return {"occurred_at": t.isoformat()}

    yield "event_id", lambda: {"event_id": _need(_g(row, "event_id"), "event_id")[:200]}
    yield "site", site
    yield "activity", lambda: {"activity": _activity(_g(row, "activity"), lk)}
    yield "occurred_at", when
    yield "quantity", lambda: {"quantity": _num(_g(row, "quantity"), "quantity")}
    yield "unit", lambda: {"unit": (_g(row, "unit") or "units").lower()[:20]}
    yield "customer", lambda: {"customer": _customer(_g(row, "customer"), lk)}
    yield "action", lambda: {"action": _enum((_g(row, "action") or "create").lower(), ("create", "correct", "cancel"), "action", {"update": "correct", "delete": "cancel", "void": "cancel"})}
    yield "revision", lambda: {"revision": (int(_num(_g(row, "revision"), "revision", minimum=1, maximum=1e6)) if _g(row, "revision") else None)}
    yield "source", lambda: {"source": (_g(row, "source") or "default").lower()[:60]}


def _bool(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes", "y")


def _hhmm(v: str, name: str) -> str:
    import re as _re
    if not _re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v.strip()):
        raise ImportProblem(f"{name} must be 24-hour HH:MM (got '{v}')")
    return v.strip()


def _zones(row, lk):
    def zid():
        v = _need(_g(row, "zone_id"), "zone_id")
        if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,40}", v):
            raise ImportProblem("zone_id may use letters, numbers, underscore and hyphen only (up to 40)")
        return {"zone_id": v}

    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "zone_id", zid
    yield "zone_name", lambda: {"zone_name": _need(_g(row, "zone_name"), "zone_name")[:200]}


def _activity_roles(row, lk):
    state: dict = {}

    def site():
        s = _site(_g(row, "site"), lk)[0]
        state["site"] = s
        return {"site": s}

    def zone():
        if "site" not in state:
            raise ImportProblem("cannot read zone_id until site is valid")
        z = _need(_g(row, "zone_id"), "zone_id")
        if (state["site"], z) not in lk.zone_ids:
            raise ImportProblem(f"zone '{z}' is not set up at site '{state['site']}'. Add it under Zones first.")
        return {"zone_id": z}

    yield "site", site
    yield "activity", lambda: {"activity": _activity(_g(row, "activity"), lk)}
    yield "role", lambda: {"role": _need(_g(row, "role"), "role").lower()[:80]}
    yield "zone_id", zone
    yield "weight", lambda: {"weight": _num(_g(row, "weight"), "weight", minimum=0.0001, maximum=1000) if _g(row, "weight") else 1.0}


def _operating_calendar(row, lk):
    state: dict = {}

    def flags():
        is24, closed = _bool(_g(row, "is_24h")), _bool(_g(row, "is_closed"))
        if is24 and closed:
            raise ImportProblem("a weekday cannot be both 24-hour and closed")
        state["is_24h"], state["is_closed"] = is24, closed
        return {"is_24h": is24, "is_closed": closed}

    def times():
        o, c = _g(row, "open_time"), _g(row, "close_time")
        is24, closed = state.get("is_24h", False), state.get("is_closed", False)
        if is24 or closed:
            if o or c:
                raise ImportProblem("open_time/close_time must be blank when 24-hour or closed is set")
            return {"open_time": None, "close_time": None}
        if not (o and c):
            raise ImportProblem("every weekday needs is_24h, is_closed, or both open_time and close_time")
        ot, ct = _hhmm(o, "open_time"), _hhmm(c, "close_time")
        if ot == ct:
            raise ImportProblem("open_time and close_time cannot be equal — use the 24-hour or closed setting instead")
        return {"open_time": ot, "close_time": ct}

    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "weekday", lambda: {"weekday": _enum(_g(row, "weekday").lower(), WEEKDAYS, "weekday")}
    yield "is_24h", flags
    yield "open_time", times


def _shift_templates(row, lk):
    def weekdays():
        raw = [w.strip().lower() for w in _g(row, "weekdays").replace(",", ";").split(";") if w.strip()]
        if not raw:
            raise ImportProblem("weekdays is required")
        bad = [w for w in raw if w not in WEEKDAYS]
        if bad:
            raise ImportProblem(f"weekdays must be from {', '.join(WEEKDAYS)} (got '{bad[0]}')")
        return {"weekdays": sorted(set(raw), key=WEEKDAYS.index)}

    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "shift_code", lambda: {"shift_code": _need(_g(row, "shift_code"), "shift_code")[:40]}
    yield "start_time", lambda: {"start_time": _hhmm(_need(_g(row, "start_time"), "start_time"), "start_time")}
    yield "end_time", lambda: {"end_time": _hhmm(_need(_g(row, "end_time"), "end_time"), "end_time")}
    yield "weekdays", weekdays
    yield "effective_from", lambda: {"effective_from": (parse_local_date(_g(row, "effective_from")) if _g(row, "effective_from") else datetime.now(timezone.utc).date()).isoformat()}


def _shift_breaks(row, lk):
    state: dict = {}

    def code():
        if "site" not in state:
            raise ImportProblem("cannot read shift_code until site is valid")
        c = _need(_g(row, "shift_code"), "shift_code")[:40]
        if (state["site"], c) not in lk.shift_templates:
            raise ImportProblem(f"shift_code '{c}' is not an active shift template at site '{state['site']}'. Add it under Shift templates first.")
        return {"shift_code": c}

    def site():
        s = _site(_g(row, "site"), lk)[0]
        state["site"] = s
        return {"site": s}

    yield "site", site
    yield "shift_code", code
    yield "starts_after_minutes", lambda: {"starts_after_minutes": int(_num(_g(row, "starts_after_minutes"), "starts_after_minutes", minimum=0, maximum=1440))}
    yield "duration_minutes", lambda: {"duration_minutes": int(_num(_g(row, "duration_minutes"), "duration_minutes", minimum=1, maximum=1440))}
    yield "is_paid", lambda: {"is_paid": _bool(_g(row, "is_paid"))}


def _process_templates(row, lk):
    def code():
        v = _need(_g(row, "process_code"), "process_code")[:60]
        if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,60}", v):
            raise ImportProblem("process_code may use letters, numbers, underscore and hyphen only (up to 60)")
        return {"process_code": v}

    def cust():
        c = _g(row, "customer_id")
        return {"customer_id": _customer(c, lk) if c else None}

    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "process_code", code
    yield "customer_id", cust


def _process_steps(row, lk):
    state: dict = {}

    def site():
        s = _site(_g(row, "site"), lk)[0]
        state["site"] = s
        return {"site": s}

    def code():
        if "site" not in state:
            raise ImportProblem("cannot read process_code until site is valid")
        c = _need(_g(row, "process_code"), "process_code")
        if (state["site"], c) not in lk.process_templates:
            raise ImportProblem(f"process_code '{c}' is not set up at site '{state['site']}'. Add it under Process templates first.")
        return {"process_code": c}

    def equipment():
        e = _g(row, "equipment_id")
        if not e:
            return {"equipment_id": None}
        if "site" not in state:
            raise ImportProblem("cannot read equipment_id until site is valid")
        if (state["site"], e) not in lk.equipment_ids:
            raise ImportProblem(f"equipment_id '{e}' is not set up at site '{state['site']}'. Add it under Equipment first.")
        return {"equipment_id": e}

    def zone():
        z = _g(row, "zone_id")
        if not z:
            return {"zone_id": None}
        if "site" not in state:
            raise ImportProblem("cannot read zone_id until site is valid")
        if (state["site"], z) not in lk.zone_ids:
            raise ImportProblem(f"zone '{z}' is not set up at site '{state['site']}'. Add it under Zones first.")
        return {"zone_id": z}

    yield "site", site
    yield "process_code", code
    yield "sequence", lambda: {"sequence": int(_num(_g(row, "sequence"), "sequence", minimum=1, maximum=100))}
    yield "activity", lambda: {"activity": _activity(_g(row, "activity"), lk)}
    yield "lag_minutes", lambda: {"lag_minutes": int(_num(_g(row, "lag_minutes"), "lag_minutes", minimum=0, maximum=10080)) if _g(row, "lag_minutes") else 0}
    yield "equipment_id", equipment
    yield "zone_id", zone


def _orders(row, lk):
    state: dict = {}

    def site():
        s, tz = _site(_g(row, "site"), lk)
        state["site"], state["tz"] = s, tz
        return {"site": s}

    def received():
        if "tz" not in state:
            raise ImportProblem("cannot read order_received until site is valid")
        t = parse_moment(_g(row, "order_received"), state["tz"])
        state["received"] = t
        return {"order_received": t.isoformat()}

    def due():
        if "received" not in state:
            raise ImportProblem("cannot read despatch_due until order_received is valid")
        t = parse_moment(_g(row, "despatch_due"), state["tz"])
        if t <= state["received"]:
            raise ImportProblem("despatch_due must be after order_received")
        return {"despatch_due": t.isoformat()}

    def qty():
        u, l = _g(row, "units"), _g(row, "lines")
        if not u and not l:
            raise ImportProblem("units or lines is required")
        return {"units": _num(u, "units", minimum=1e-6) if u else None, "lines": _num(l, "lines", minimum=1e-6) if l else None}

    def code():
        if "site" not in state:
            raise ImportProblem("cannot read process_code until site is valid")
        c = _need(_g(row, "process_code"), "process_code")
        if (state["site"], c) not in lk.process_templates:
            raise ImportProblem(f"process_code '{c}' is not set up at site '{state['site']}'. Add it under Process templates first.")
        return {"process_code": c}

    yield "site", site
    yield "order_id", lambda: {"order_id": _need(_g(row, "order_id"), "order_id")[:80]}
    yield "customer_id", lambda: {"customer_id": _customer(_g(row, "customer_id"), lk)}
    yield "order_received", received
    yield "despatch_due", due
    yield "units", qty
    yield "unit", lambda: {"unit": (_g(row, "unit") or "units").lower()[:20]}
    yield "process_code", code


def _worker_activity_rates(row, lk):
    def ref():
        r = _need(_g(row, "worker_ref"), "worker_ref")
        if r not in lk.workers_by_ref:
            raise ImportProblem(f"worker_ref '{r}' is not a person from your staff upload. Upload staff first.")
        return {"worker_ref": r}

    yield "worker_ref", ref
    yield "activity", lambda: {"activity": _activity(_g(row, "activity"), lk)}
    yield "unit", lambda: {"unit": (_g(row, "unit") or "units").lower()[:20]}
    yield "rate_per_hour", lambda: {"rate_per_hour": _num(_g(row, "rate_per_hour"), "rate_per_hour", minimum=0.01, maximum=100000)}
    yield "effective_from", lambda: {"effective_from": (parse_local_date(_g(row, "effective_from")) if _g(row, "effective_from") else datetime.now(timezone.utc).date()).isoformat()}


def _unit_conversions(row, lk):
    def units():
        f, t = _need(_g(row, "from_unit"), "from_unit").lower()[:20], _need(_g(row, "to_unit"), "to_unit").lower()[:20]
        if f == t:
            raise ImportProblem("from_unit and to_unit must differ")
        return {"from_unit": f, "to_unit": t}

    yield "activity", lambda: {"activity": (_g(row, "activity").lower()[:80] or None)}
    yield "from_unit", units
    yield "factor", lambda: {"factor": _num(_g(row, "factor"), "factor", minimum=1e-4, maximum=1e6)}


def _fill_priorities(row, lk):
    def scope():
        v = _g(row, "scope").lower()
        if v == "customer":
            raise ImportProblem("customer-scoped fill priority is not supported in this release — use activity or employment_type")
        return {"scope": _enum(v, ("activity", "employment_type"), "scope")}

    yield "scope", scope
    yield "value", lambda: {"value": _need(_g(row, "value"), "value")[:80]}
    yield "priority", lambda: {"priority": int(_num(_g(row, "priority"), "priority", minimum=0, maximum=10000))}


def _absenteeism(row, lk):
    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "activity", lambda: {"activity": (_g(row, "activity").lower()[:80] or None)}
    yield "weekday", lambda: {"weekday": (_enum(_g(row, "weekday").lower(), WEEKDAYS, "weekday") if _g(row, "weekday") else None)}
    yield "shift_code", lambda: {"shift_code": (_g(row, "shift_code")[:40] or None)}
    yield "absence_pct", lambda: {"absence_pct": _num(_g(row, "absence_pct"), "absence_pct", minimum=0, maximum=99.9999) / 100}


def _equipment(row, lk):
    def eid():
        v = _need(_g(row, "equipment_id"), "equipment_id")[:60]
        if not __import__("re").fullmatch(r"[A-Za-z0-9_-]{1,60}", v):
            raise ImportProblem("equipment_id may use letters, numbers, underscore and hyphen only (up to 60)")
        return {"equipment_id": v}

    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "equipment_id", eid
    yield "description", lambda: {"description": _need(_g(row, "description"), "description")[:200]}
    yield "quantity_available", lambda: {"quantity_available": int(_num(_g(row, "quantity_available"), "quantity_available", minimum=1, maximum=100000))}


def _headcount_limits(row, lk):
    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "activity", lambda: {"activity": _activity(_g(row, "activity"), lk)}
    yield "shift_code", lambda: {"shift_code": (_g(row, "shift_code")[:40] or None)}
    yield "min_headcount", lambda: {"min_headcount": int(_num(_g(row, "min_headcount"), "min_headcount", minimum=0, maximum=100000))}
    yield "max_headcount", lambda: {"max_headcount": int(_num(_g(row, "max_headcount"), "max_headcount", minimum=0, maximum=100000))}


def _grade_rates(row, lk):
    def grade():
        return {"position_grade": _g(row, "position_grade")[:80] or None}

    def provider():
        p = _g(row, "provider_id")
        if not p:
            return {"provider_id": None}
        if p not in lk.labour_providers:
            raise ImportProblem(f"provider_id '{p}' is not a labour provider on file")
        return {"provider_id": p}

    def dates():
        ef = parse_local_date(_g(row, "effective_from")) if _g(row, "effective_from") else datetime.now(timezone.utc).date()
        et = parse_local_date(_g(row, "effective_to")) if _g(row, "effective_to") else None
        if et is not None and et <= ef:
            raise ImportProblem("effective_to must be after effective_from")
        return {"effective_from": ef.isoformat(), "effective_to": et.isoformat() if et else None}

    yield "employment_type", lambda: {"employment_type": _enum(_g(row, "employment_type").lower().replace(" ", "_").replace("-", "_"), ("permanent", "casual", "labour_hire"), "employment_type")}
    yield "role", lambda: {"role": _need(_g(row, "role"), "role").lower()[:80]}
    yield "position_grade", grade
    yield "provider_id", provider
    yield "hourly_rate", lambda: {"hourly_rate": _num(_g(row, "hourly_rate"), "hourly_rate", minimum=0.01, maximum=10000)}
    yield "overtime_multiplier", lambda: {"overtime_multiplier": _num(_g(row, "overtime_multiplier"), "overtime_multiplier", minimum=1.0, maximum=5.0) if _g(row, "overtime_multiplier") else None}
    yield "surcharge", lambda: {"surcharge": _num(_g(row, "surcharge"), "surcharge", minimum=0.0, maximum=10000) if _g(row, "surcharge") else None}
    yield "currency", lambda: {"currency": (_g(row, "currency").upper()[:3] or "AUD")}
    yield "effective_from", dates


def _productivity_loss(row, lk):
    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "type", lambda: {"type": _enum(_g(row, "type").lower(), ("congestion", "off_task"), "type")}
    yield "activity", lambda: {"activity": (_g(row, "activity").lower()[:80] or None)}
    yield "weekday", lambda: {"weekday": (_enum(_g(row, "weekday").lower(), WEEKDAYS, "weekday") if _g(row, "weekday") else None)}
    yield "shift_code", lambda: {"shift_code": (_g(row, "shift_code")[:40] or None)}
    yield "percent_loss", lambda: {"percent_loss": _num(_g(row, "percent_loss"), "percent_loss", minimum=0, maximum=99.9999) / 100 if _g(row, "percent_loss") else None}
    yield "off_task_hours", lambda: {"off_task_hours": _num(_g(row, "off_task_hours"), "off_task_hours", minimum=0, maximum=24) if _g(row, "off_task_hours") else None}


def _staging_capacity(row, lk):
    state: dict = {}

    def site():
        s = _site(_g(row, "site"), lk)[0]
        state["site"] = s
        return {"site": s}

    def zid():
        if "site" not in state:
            raise ImportProblem("cannot read zone_id until site is valid")
        z = _need(_g(row, "zone_id"), "zone_id")[:40]
        if (state["site"], z) not in lk.zone_ids:
            raise ImportProblem(f"zone '{z}' is not set up at site '{state['site']}'. Add it under Zones first.")
        return {"zone_id": z}

    yield "site", site
    yield "zone_id", zid
    yield "capacity", lambda: {"capacity": _num(_g(row, "capacity"), "capacity", minimum=0.0001, maximum=1e9)}
    yield "unit", lambda: {"unit": _need(_g(row, "unit"), "unit").lower()[:20]}


def _staging_movements(row, lk):
    state: dict = {}

    def site():
        s, tz = _site(_g(row, "site"), lk)
        state["site"], state["tz"] = s, tz
        return {"site": s}

    def zone():
        if "site" not in state:
            raise ImportProblem("cannot read zone_id until site is valid")
        z = _need(_g(row, "zone_id"), "zone_id")
        if (state["site"], z) not in lk.staging_units:
            raise ImportProblem(f"zone '{z}' has no Staging capacity row at site '{state['site']}'. Add one first.")
        state["zone"] = z
        return {"zone_id": z}

    def unit():
        if "zone" not in state:
            raise ImportProblem("cannot read unit until zone_id is valid")
        u = _need(_g(row, "unit"), "unit").lower()[:20]
        expected = lk.staging_units[(state["site"], state["zone"])]
        if u != expected:
            raise ImportProblem(f"unit '{u}' does not match this zone's capacity unit '{expected}' — add a conversion or correct the upload before capacity can be validated")
        return {"unit": u}

    yield "site", site
    yield "zone_id", zone
    yield "occurred_at", lambda: {"occurred_at": parse_moment(_g(row, "occurred_at"), state["tz"]).isoformat()}
    yield "movement_type", lambda: {"movement_type": _enum(_g(row, "movement_type").lower(), ("initial", "arrival", "departure"), "movement_type")}
    yield "quantity", lambda: {"quantity": _num(_g(row, "quantity"), "quantity", minimum=0)}
    yield "unit", unit


def _weekly_availability(row, lk):
    def ref():
        r = _need(_g(row, "worker_ref"), "worker_ref")
        if r not in lk.workers_by_ref:
            raise ImportProblem(f"worker_ref '{r}' is not a person from your staff upload. Upload staff first.")
        return {"worker_ref": r}

    def times():
        e, f = _g(row, "earliest_start"), _g(row, "latest_finish")
        if bool(e) != bool(f):
            raise ImportProblem("give both earliest_start and latest_finish, or neither")
        if not e:
            return {"earliest_start": None, "latest_finish": None}
        return {"earliest_start": _hhmm(e, "earliest_start"), "latest_finish": _hhmm(f, "latest_finish")}

    yield "worker_ref", ref
    yield "weekday", lambda: {"weekday": _enum(_g(row, "weekday").lower(), WEEKDAYS, "weekday")}
    yield "available", lambda: {"available": _bool(_g(row, "available")) if _g(row, "available") else True}
    yield "earliest_start", times


def _day_rates(row, lk):
    yield "activity", lambda: {"activity": _activity(_g(row, "activity"), lk)}
    yield "weekday", lambda: {"weekday": _enum(_g(row, "weekday").lower(), WEEKDAYS, "weekday")}
    yield "rate_per_hour", lambda: {"rate_per_hour": _num(_g(row, "rate_per_hour"), "rate_per_hour", minimum=0.01, maximum=100000)}


def _award_rules(row, lk):
    yield "award_code", lambda: {"award_code": _need(_g(row, "award_code"), "award_code")[:80]}
    yield "ordinary_hours_per_day", lambda: {"ordinary_hours_per_day": _num(_g(row, "ordinary_hours_per_day"), "ordinary_hours_per_day", minimum=0.1, maximum=24)}
    yield "overtime_multiplier", lambda: {"overtime_multiplier": _num(_g(row, "overtime_multiplier"), "overtime_multiplier", minimum=1.0, maximum=5.0)}


def _award_eligibility_restrictions(row, lk):
    yield "award_code", lambda: {"award_code": _need(_g(row, "award_code"), "award_code")[:80]}
    yield "activity", lambda: {"activity": _activity(_g(row, "activity"), lk)}


def _indirect_headcount(row, lk):
    yield "site", lambda: {"site": _site(_g(row, "site"), lk)[0]}
    yield "role", lambda: {"role": _need(_g(row, "role"), "role").lower()[:80]}
    yield "weekday", lambda: {"weekday": _enum(_g(row, "weekday").lower(), WEEKDAYS, "weekday")}
    yield "start_time", lambda: {"start_time": _hhmm(_need(_g(row, "start_time"), "start_time"), "start_time")}
    yield "end_time", lambda: {"end_time": _hhmm(_need(_g(row, "end_time"), "end_time"), "end_time")}
    yield "headcount", lambda: {"headcount": int(_num(_g(row, "headcount"), "headcount", minimum=0, maximum=10000))}


def _need(v: str, name: str) -> str:
    if not v:
        raise ImportProblem(f"{name} is required")
    return v


def _enum(v: str, choices: tuple[str, ...], name: str, aliases: dict[str, str] | None = None) -> str:
    v = (aliases or {}).get(v, v)
    if v not in choices:
        raise ImportProblem(f"{name} must be one of: {', '.join(choices)} (got '{v}')")
    return v


_VALIDATORS = {("master", "workers"): _workers, ("master", "work_standards"): _standards, ("master", "sites"): _sites, ("master", "customers"): _customers, ("master", "availability"): _availability, ("master", "rates"): _rates,
               ("master", "zones"): _zones, ("master", "activity_roles"): _activity_roles, ("master", "operating_calendar"): _operating_calendar, ("master", "shift_templates"): _shift_templates, ("master", "shift_breaks"): _shift_breaks,
               ("master", "process_templates"): _process_templates, ("master", "process_steps"): _process_steps, ("master", "orders"): _orders,
               ("master", "worker_activity_rates"): _worker_activity_rates, ("master", "unit_conversions"): _unit_conversions,
               ("master", "fill_priorities"): _fill_priorities, ("master", "absenteeism"): _absenteeism, ("master", "equipment"): _equipment, ("master", "headcount_limits"): _headcount_limits,
               ("master", "grade_rates"): _grade_rates, ("master", "productivity_loss"): _productivity_loss, ("master", "staging_capacity"): _staging_capacity, ("master", "staging_movements"): _staging_movements,
               ("master", "indirect_headcount"): _indirect_headcount, ("master", "weekly_availability"): _weekly_availability,
               ("master", "day_rates"): _day_rates, ("master", "award_rules"): _award_rules, ("master", "award_eligibility_restrictions"): _award_eligibility_restrictions,
               ("forecast", None): _forecast, ("transactions", None): _transactions, ("bulk", None): _bulk}


def row_key(data_class: str, entity: str | None, n: dict) -> tuple:
    """Identity of a row inside one file, for duplicate detection."""
    if data_class == "master":
        return {"workers": lambda: (n["worker_ref"],), "work_standards": lambda: (n["activity"],), "sites": lambda: (n["site_id"],), "customers": lambda: (n["customer_id"],),
                "availability": lambda: (n["worker_ref"], n["kind"], n["start_at"]), "rates": lambda: (n["employment_type"], n["role"]),
                "zones": lambda: (n["site"], n["zone_id"]), "activity_roles": lambda: (n["site"], n["activity"], n["role"], n["zone_id"]),
                "operating_calendar": lambda: (n["site"], n["weekday"]), "shift_templates": lambda: (n["site"], n["shift_code"]),
                "shift_breaks": lambda: (n["site"], n["shift_code"], n["starts_after_minutes"], n["duration_minutes"]),
                "process_templates": lambda: (n["site"], n["process_code"], n.get("customer_id")), "process_steps": lambda: (n["site"], n["process_code"], n["sequence"]),
                "orders": lambda: (n["site"], n["order_id"]), "worker_activity_rates": lambda: (n["worker_ref"], n["activity"], n["effective_from"]),
                "unit_conversions": lambda: (n.get("activity"), n["from_unit"], n["to_unit"]),
                "fill_priorities": lambda: (n["scope"], n["value"]), "absenteeism": lambda: (n["site"], n.get("activity"), n.get("weekday"), n.get("shift_code")),
                "equipment": lambda: (n["site"], n["equipment_id"]), "headcount_limits": lambda: (n["site"], n["activity"], n.get("shift_code")),
                "grade_rates": lambda: (n["employment_type"], n["role"], n.get("position_grade"), n.get("provider_id"), n["effective_from"]),
                "productivity_loss": lambda: (n["site"], n["type"], n.get("activity"), n.get("weekday"), n.get("shift_code")),
                "staging_capacity": lambda: (n["site"], n["zone_id"]), "staging_movements": lambda: (n["site"], n["zone_id"], n["occurred_at"], n["movement_type"]),
                "indirect_headcount": lambda: (n["site"], n["role"], n["weekday"], n["start_time"], n["end_time"]),
                "weekly_availability": lambda: (n["worker_ref"], n["weekday"]),
                "day_rates": lambda: (n["activity"], n["weekday"]), "award_rules": lambda: (n["award_code"],),
                "award_eligibility_restrictions": lambda: (n["award_code"], n["activity"])}[entity]()
    if data_class == "transactions":
        return (n["source"], n["event_id"], n.get("revision"), n["action"])
    return (n["site"], n["activity"], n["bucket_start"], n["bucket_minutes"], n.get("customer"))


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
