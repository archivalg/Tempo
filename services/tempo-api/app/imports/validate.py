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
    a = v.strip()
    if not a:
        raise ImportProblem("activity is required")
    if a not in lk.activities:
        raise ImportProblem(f"activity '{a}' has no work standard. Add it under Work standards first (or correct the spelling).")
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


def _need(v: str, name: str) -> str:
    if not v:
        raise ImportProblem(f"{name} is required")
    return v


def _enum(v: str, choices: tuple[str, ...], name: str, aliases: dict[str, str] | None = None) -> str:
    v = (aliases or {}).get(v, v)
    if v not in choices:
        raise ImportProblem(f"{name} must be one of: {', '.join(choices)} (got '{v}')")
    return v


_VALIDATORS = {("master", "workers"): _workers, ("master", "work_standards"): _standards, ("master", "sites"): _sites, ("master", "customers"): _customers, ("master", "availability"): _availability, ("master", "rates"): _rates, ("forecast", None): _forecast, ("transactions", None): _transactions, ("bulk", None): _bulk}


def row_key(data_class: str, entity: str | None, n: dict) -> tuple:
    """Identity of a row inside one file, for duplicate detection."""
    if data_class == "master":
        return {"workers": lambda: (n["worker_ref"],), "work_standards": lambda: (n["activity"],), "sites": lambda: (n["site_id"],), "customers": lambda: (n["customer_id"],),
                "availability": lambda: (n["worker_ref"], n["kind"], n["start_at"]), "rates": lambda: (n["employment_type"], n["role"])}[entity]()
    if data_class == "transactions":
        return (n["source"], n["event_id"], n.get("revision"), n["action"])
    return (n["site"], n["activity"], n["bucket_start"], n["bucket_minutes"], n.get("customer"))


def canonical_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
