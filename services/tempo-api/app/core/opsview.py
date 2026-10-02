"""Read models for the Overview, Roster Planner and Live Attendance screens.

Everything here is derived from stored source records; nothing is invented. Where an input is
missing the field is `null` with a reason, never zero (Blueprint §3.1: "No verified data").
Definitions are versioned in `METRIC_DEFS` and returned with each KPI.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions_engine import STATUS_OPEN, source_is_fresh
from app.core.policy import resolve_policy
from app.models.canonical import (
    ActivityRoleZoneMap, AttendanceSession, DemandBucket, LabourCostRule, ShiftAssignment, Worker, WorkStandard,
)
from app.models.directory import DataSourceStatus, ExceptionCase, Site, WorkerPerson, Zone
from app.models.runs import ActionRequest, OptimisationRun, OptimisationRunSite, Recommendation

METRIC_VERSION = "tempo-metrics-1.0"
METRIC_DEFS = {
    "scheduled_workers": "Distinct workers with a published (committed) shift starting in the site's local day.",
    "clocked_in": "Workers with an open attendance session (clocked in, not yet out) as of the last attendance update.",
    "coverage": "Σ over the day's hours of min(rostered hours, required hours) ÷ Σ required hours. Required hours = forecast (else actual) units × work-standard seconds ÷ 3600. Planned basis, not live.",
    "work_units": "Units actually received so far today ÷ forecast units for the whole local day (the forecast model; see the method shown on the Demand page).",
    "labour_cost": "Planned = Σ published shift hours × the matching cost rule's rate. Actual (estimate) = Σ attendance hours to date × rate; attendance not yet approved is an estimate, not payable actual.",
    "open_exceptions": "Exceptions in state detected/triaged/assigned at this site.",
}


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def local_day_bounds(tz: ZoneInfo, day_iso: str | None, now: datetime) -> tuple[datetime, datetime, str]:
    d = datetime.fromisoformat(day_iso).date() if day_iso else now.astimezone(tz).date()
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    nxt = d + timedelta(days=1)
    return start.astimezone(timezone.utc), datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz).astimezone(timezone.utc), d.isoformat()


def get_site(db: Session, tenant_id: str, site_id: str, allowed: list[str]) -> Site | None:
    if site_id not in allowed:
        return None
    return db.get(Site, (tenant_id, site_id))


def source_view(src: DataSourceStatus, now: datetime) -> dict:
    age = None if src.last_success_at is None else int((now - _aware(src.last_success_at)).total_seconds())
    fresh = source_is_fresh(src, now)
    effective = src.mode if fresh or src.mode in ("simulated",) else ("stale" if src.mode in ("live", "stale") else src.mode)
    if src.mode == "simulated" and not fresh:
        effective = "simulated"
    return {"key": src.source_key, "label": src.label, "kind": src.kind, "mode": effective, "declared_mode": src.mode,
            "last_success_at": src.last_success_at, "age_seconds": age, "fresh": fresh, "note": src.note}


def site_sources(db: Session, tenant_id: str, site_id: str, now: datetime) -> list[dict]:
    rows = db.scalars(select(DataSourceStatus).where(DataSourceStatus.tenant_id == tenant_id, DataSourceStatus.site_id == site_id)).all()
    return [source_view(r, now) for r in rows]


def _standards(db: Session, tenant_id: str, at: datetime) -> dict[str, float]:
    out: dict[str, float] = {}
    for w in db.scalars(select(WorkStandard).where(WorkStandard.tenant_id == tenant_id)):
        if _aware(w.effective_from) <= at and (w.effective_to is None or _aware(w.effective_to) > at):
            out[w.activity] = w.time_per_unit_seconds
    return out


METHOD_LABEL = {"holt_linear_weekly": "Holt linear trend with a day-of-week pattern", "holt_linear_weekly_partial": "Holt linear trend; day-of-week pattern for some activities only",
                "holt_linear": "Holt linear trend (no weekly pattern — under two weeks of daily history, or an older run)"}


def method_label(run) -> str:
    """What the forecast actually did, taken from the run itself (older runs predate the weekly pattern and the supplied-forecast option)."""
    res = (run.result or {}) if run else {}
    src, ver = res.get("forecast_source"), ", ".join(res.get("supplied_versions") or [])
    if src == "supplied":
        return f"Customer-supplied forecast ({ver})"
    base = METHOD_LABEL.get(res.get("method"), METHOD_LABEL["holt_linear"])
    return f"{base}; customer-supplied forecast ({ver}) for the activities it covers" if src == "mixed" else base


def _latest_forecast(db: Session, tenant_id: str, site_id: str) -> tuple[OptimisationRun | None, list[dict]]:
    """Newest forecast run for the site, plus forecast rows merged across recent runs: for any bucket, the most
    recent run that covers it wins (so a forecast for next week never hides this week's)."""
    runs = db.scalars(
        select(OptimisationRun).join(OptimisationRunSite, OptimisationRunSite.run_id == OptimisationRun.run_id)
        .where(OptimisationRun.tenant_id == tenant_id, OptimisationRun.run_type == "demand_forecast",
               OptimisationRun.status.in_(("completed", "completed_with_warnings")), OptimisationRunSite.site_id == site_id)
        .order_by(OptimisationRun.created_at.desc()).limit(8)).all()
    if not runs:
        return None, []
    merged: dict[tuple[str, str], dict] = {}
    for run in reversed(runs):  # oldest first, so newer runs overwrite
        for r in (run.result or {}).get("forecast", []):
            merged[(r["activity"], str(r["bucket_start"]))] = r
    return runs[0], list(merged.values())


def _rates(db: Session, tenant_id: str) -> dict[tuple[str, str], float]:
    return {(r.labour_type, r.role): float(r.rate) for r in db.scalars(select(LabourCostRule).where(LabourCostRule.tenant_id == tenant_id))}


def _site_shifts(db: Session, tenant_id: str, site_id: str, start: datetime, end: datetime, status: str | None = "committed"):
    q = (select(ShiftAssignment, Worker).join(Worker, Worker.worker_id == ShiftAssignment.worker_id)
         .where(ShiftAssignment.tenant_id == tenant_id, Worker.home_site == site_id,
                ShiftAssignment.end_at > start, ShiftAssignment.start_at < end))
    if status:
        q = q.where(ShiftAssignment.status == status)
    return db.execute(q).all()


def overview(db: Session, tenant_id: str, site: Site, day_iso: str | None, now: datetime, *, can_see_rates: bool, can_see_names: bool) -> dict:
    tz = ZoneInfo(site.timezone)
    d_start, d_end, day = local_day_bounds(tz, day_iso, now)
    sources = site_sources(db, tenant_id, site.site_id, now)
    att_src = next((s for s in sources if s["key"] == "attendance"), None)
    att_verified = bool(att_src and att_src["fresh"] and att_src["mode"] in ("live", "simulated"))
    standards = _standards(db, tenant_id, now)
    fc_run, fc_rows = _latest_forecast(db, tenant_id, site.site_id)
    zone_map = db.scalars(select(ActivityRoleZoneMap).where(ActivityRoleZoneMap.tenant_id == tenant_id, ActivityRoleZoneMap.site_id == site.site_id)).all()
    zones = list(db.scalars(select(Zone).where(Zone.tenant_id == tenant_id, Zone.site_id == site.site_id).order_by(Zone.sort_order)))

    # hourly buckets across the local day (23/25 on DST days)
    hours: list[datetime] = []
    t = d_start
    while t < d_end:
        hours.append(t)
        t += timedelta(hours=1)
    idx = {h: i for i, h in enumerate(hours)}

    def hour_of(dt: datetime) -> datetime:
        dt = _aware(dt)
        return dt.replace(minute=0, second=0, microsecond=0)

    actual: dict[datetime, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for b in db.scalars(select(DemandBucket).where(DemandBucket.tenant_id == tenant_id, DemandBucket.site_id == site.site_id,
                                                   DemandBucket.bucket_minutes == 60, DemandBucket.interval_start >= d_start, DemandBucket.interval_start < d_end)):
        actual[hour_of(b.interval_start)][b.activity] += b.volume
    fc: dict[datetime, dict[str, dict]] = defaultdict(dict)
    daily = _daily_rows(fc_rows)
    if daily:
        fc = _spread_daily_forecast(db, tenant_id, site.site_id, tz, fc_rows, hours, d_start, d_end)
    else:
        for r in fc_rows:
            bs = datetime.fromisoformat(r["bucket_start"]) if isinstance(r["bucket_start"], str) else r["bucket_start"]
            if d_start <= bs < d_end:
                fc[hour_of(bs)][r["activity"]] = r

    shifts = _site_shifts(db, tenant_id, site.site_id, d_start, d_end)
    zone_activity = defaultdict(list)  # zone -> [(activity, weight)]
    for m in zone_map:
        zone_activity[m.zone].append((m.activity, m.weight))
    act_zone = defaultdict(list)
    for m in zone_map:
        act_zone[m.activity].append((m.zone, m.weight))

    staffed_by_hour_zone: dict[tuple[datetime, str], float] = defaultdict(float)
    for sh, _w in shifts:
        s, e = _aware(sh.start_at), _aware(sh.end_at)
        for h in hours:
            ov = (min(e, h + timedelta(hours=1)) - max(s, h)).total_seconds() / 3600
            if ov > 0:
                staffed_by_hour_zone[(h, sh.zone)] += ov

    hourly = []
    required_by_hour_zone: dict[tuple[datetime, str], float] = defaultdict(float)
    have_forecast = bool(fc)
    conf = ((fc_run.explanation or {}).get("confidence") if fc_run else None)
    for h in hours:
        a_units = sum(actual[h].values()) if h in actual and h <= now else None
        f_units = sum(v["point"] for v in fc[h].values()) if h in fc else None
        lo = sum(v["lower"] for v in fc[h].values()) if h in fc else None
        hi = sum(v["upper"] for v in fc[h].values()) if h in fc else None
        basis = fc[h] if h in fc else None
        req_h = None
        if basis is not None or h in actual:
            req_h = 0.0
            for act in set((basis or {}).keys()) | set(actual[h].keys()):
                units = (basis[act]["point"] if basis and act in basis else actual[h].get(act, 0.0))
                sec = standards.get(act)
                if sec is None:
                    req_h = None
                    break
                hrs = units * sec / 3600
                req_h += hrs
                tot_w = sum(w for _, w in act_zone.get(act, [])) or 1.0
                for z, w in act_zone.get(act, []):
                    required_by_hour_zone[(h, z)] += hrs * w / tot_w
        staffed = sum(v for (hh, _z), v in staffed_by_hour_zone.items() if hh == h)
        cap_units = 0.0
        for (hh, z), v in staffed_by_hour_zone.items():
            if hh != h:
                continue
            acts = zone_activity.get(z, [])
            if acts:
                a, _w = acts[0]
                if a in standards:
                    cap_units += v * 3600 / standards[a]
        hourly.append({"hour_start": h, "actual_units": a_units, "forecast_units": f_units, "forecast_lower": lo, "forecast_upper": hi,
                       "capacity_units": round(cap_units, 1) if staffed_by_hour_zone else None, "staffed_hours": round(staffed, 2),
                       "required_hours": None if req_h is None else round(req_h, 2),
                       "source": {"actual": "demand_bucket (tempo_native/simulated)", "forecast": (f"run {fc_run.run_id}" if fc_run else None)},
                       "confidence": conf})

    # heatmap: zone x shift-window
    windows = _shift_windows(shifts, tz)
    cells = []
    for z in zones:
        for wdw in windows:
            req = sum(v for (h, zz), v in required_by_hour_zone.items() if zz == z.zone_id and wdw["start"] <= h < wdw["end"])
            raw_staffed = sum(v for (h, zz), v in staffed_by_hour_zone.items() if zz == z.zone_id and wdw["start"] <= h < wdw["end"])
            if req <= 0:
                status, label = "no_demand", "No demand"
            else:
                ratio = raw_staffed / req
                status, label = ("covered", "Covered") if ratio >= 1.0 else (("risk", "At risk") if ratio >= 0.85 else ("shortage", "Shortage"))
            cells.append({"zone": z.zone_id, "zone_name": z.name, "shift": wdw["code"], "required_hours": round(req, 1), "staffed_hours": round(raw_staffed, 1),
                          "status": status, "label": label})

    # KPIs
    scheduled = {sh.worker_id for sh, _ in shifts if d_start <= _aware(sh.start_at) < d_end}
    open_sessions = db.scalars(select(AttendanceSession).join(Worker, Worker.worker_id == AttendanceSession.worker_id).where(
        AttendanceSession.tenant_id == tenant_id, Worker.home_site == site.site_id, AttendanceSession.end_at.is_(None),
        AttendanceSession.start_at <= now)).all()
    req_total = sum((h["required_hours"] or 0) for h in hourly if h["required_hours"] is not None)
    have_req = any(h["required_hours"] is not None for h in hourly)
    cov_num = sum(min(h["staffed_hours"], h["required_hours"]) for h in hourly if h["required_hours"] is not None)
    fc_day = sum(h["forecast_units"] for h in hourly if h["forecast_units"] is not None) if have_forecast else None
    act_day = sum(h["actual_units"] for h in hourly if h["actual_units"] is not None)
    any_actual = any(h["actual_units"] is not None for h in hourly)
    open_exc = db.scalars(select(ExceptionCase).where(ExceptionCase.tenant_id == tenant_id, ExceptionCase.site_id == site.site_id,
                                                      ExceptionCase.state.in_(STATUS_OPEN))).all()

    rates = _rates(db, tenant_id)
    planned_cost, missing_rate_shifts = 0.0, 0
    for sh, w in shifts:
        if d_start <= _aware(sh.start_at) < d_end:
            r = rates.get((w.employment_type, sh.role)) or rates.get((w.employment_type, "general"))
            if r is None:
                missing_rate_shifts += 1
            else:
                planned_cost += r * (_aware(sh.end_at) - _aware(sh.start_at)).total_seconds() / 3600
    actual_cost, missing_rate_att = 0.0, 0
    wmap = {w.worker_id: w for _s, w in shifts}
    for s in db.scalars(select(AttendanceSession).join(Worker, Worker.worker_id == AttendanceSession.worker_id).where(
            AttendanceSession.tenant_id == tenant_id, Worker.home_site == site.site_id, AttendanceSession.start_at >= d_start, AttendanceSession.start_at < d_end)):
        w = wmap.get(s.worker_id) or db.get(Worker, s.worker_id)
        role = next((sh.role for sh, ww in shifts if ww.worker_id == s.worker_id), "general")
        r = rates.get((w.employment_type, role)) or rates.get((w.employment_type, "general"))
        if r is None:
            missing_rate_att += 1
            continue
        actual_cost += r * ((_aware(s.end_at) or now) - _aware(s.start_at)).total_seconds() / 3600

    def kpi(key, label, value, display, unit, num=None, den=None, basis="", status="ok", drill="", reason=None):
        return {"key": key, "label": label, "value": value, "display": display if value is not None else "No verified data", "unit": unit,
                "numerator": num, "denominator": den, "definition": METRIC_DEFS.get(key, ""), "basis": basis, "status": status if value is not None else "no_data",
                "reason": reason, "drill": drill}

    stale_note = None if att_verified else "Attendance source is not verified live"
    kpis = [
        kpi("scheduled_workers", "Scheduled workers", len(scheduled) if shifts else None, f"{len(scheduled)}", "workers", basis="published roster, local day",
            status="ok", drill="/roster"),
        kpi("clocked_in", "Clocked in", len(open_sessions) if att_verified else None, f"{len(open_sessions)}", "workers", num=len(open_sessions),
            den=len(scheduled) or None, basis="attendance as of last update", status="ok", drill="/attendance", reason=stale_note),
        kpi("coverage", "Coverage (planned)", round(100 * cov_num / req_total, 1) if have_req and req_total > 0 else None,
            f"{round(100 * cov_num / req_total, 1)}%" if have_req and req_total > 0 else "", "%", num=round(cov_num, 1), den=round(req_total, 1),
            basis="rostered vs required hours, local day", drill="/demand", reason=None if have_req else "No forecast or actuals with a work standard"),
        kpi("work_units", "Work units (actual / forecast)", act_day if any_actual else None,
            f"{int(act_day):,} / {int(fc_day):,}" if any_actual and fc_day is not None else (f"{int(act_day):,}" if any_actual else ""), "units",
            num=round(act_day, 0), den=None if fc_day is None else round(fc_day, 0), basis="received to date vs day forecast", drill="/demand"),
    ]
    if can_see_rates:
        kpis.append(kpi("labour_cost", "Labour cost (plan / actual est.)", round(planned_cost, 2) if shifts and not missing_rate_shifts else None,
                        f"${planned_cost:,.0f} / ${actual_cost:,.0f}", "AUD", num=round(actual_cost, 2), den=round(planned_cost, 2),
                        basis="published shifts × cost rules; actual is an unapproved estimate",
                        reason=(f"{missing_rate_shifts} shift(s) have no cost rule" if missing_rate_shifts else None), drill="/reports"))
    kpis.append(kpi("open_exceptions", "Open exceptions", len(open_exc), f"{len(open_exc)}", "cases", basis="detected / triaged / assigned", drill="/attendance"))

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    attention = [exception_view(e, now, can_see_names, db) for e in sorted(open_exc, key=lambda e: (order.get(e.severity, 9), _aware(e.source_occurred_at)))[:8]]

    # roster preview: today + tomorrow
    preview = roster_preview(db, tenant_id, site, tz, now)
    recs = recommendations(db, tenant_id, site.site_id, now)
    return {
        "site": {"site_id": site.site_id, "name": site.name, "timezone": site.timezone, "operating_mode": site.operating_mode,
                 "is_synthetic": site.is_synthetic, "local_now": now.astimezone(tz).isoformat()},
        "day": day, "as_of": now, "metric_version": METRIC_VERSION, "data_sources": sources, "attendance_verified": att_verified,
        "forecast": {"run_id": fc_run.run_id if fc_run else None,
                     "method": f"Daily total: {method_label(fc_run)}. Hourly shape: this site's own same-weekday history, last 28 days." if fc_run else None,
                     "confidence": conf, "created_at": fc_run.created_at if fc_run else None},
        "kpis": kpis, "hourly": hourly, "heatmap": {"zones": [{"zone_id": z.zone_id, "name": z.name} for z in zones], "shifts": [
            {"code": w["code"], "start": w["start"], "end": w["end"]} for w in windows], "cells": cells},
        "attention": attention, "roster_preview": preview, "recommendations": recs,
    }


def _daily_rows(fc_rows: list[dict]) -> bool:
    if len(fc_rows) < 2:
        return False
    per_act: dict[str, list[datetime]] = defaultdict(list)
    for r in fc_rows:
        bs = datetime.fromisoformat(r["bucket_start"]) if isinstance(r["bucket_start"], str) else r["bucket_start"]
        per_act[r["activity"]].append(bs)
    for lst in per_act.values():
        lst.sort()
        if len(lst) >= 2 and (lst[1] - lst[0]) >= timedelta(hours=23):
            return True
    return False


def _spread_daily_forecast(db: Session, tenant_id: str, site_id: str, tz: ZoneInfo, fc_rows: list[dict], hours: list[datetime],
                           d_start: datetime, d_end: datetime) -> dict:
    """Daily Holt totals × the site's own historical intraday shape (same weekday, last 28 days).

    The daily total is the deployed forecast; the shape is an empirical share, so it is labelled as
    such in the API (`forecast.method`). No hourly shape history ⇒ no hourly forecast (null), not a flat guess.
    """
    hist = db.scalars(select(DemandBucket).where(
        DemandBucket.tenant_id == tenant_id, DemandBucket.site_id == site_id, DemandBucket.bucket_minutes == 60,
        DemandBucket.interval_start >= d_start - timedelta(days=28), DemandBucket.interval_start < d_start)).all()
    wd = d_start.astimezone(tz).weekday()
    per: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for b in hist:
        loc = _aware(b.interval_start).astimezone(tz)
        if loc.weekday() == wd:
            per[b.activity][loc.hour] += b.volume
    out: dict[datetime, dict[str, dict]] = defaultdict(dict)
    for r in fc_rows:
        bs = datetime.fromisoformat(r["bucket_start"]) if isinstance(r["bucket_start"], str) else r["bucket_start"]
        if not (d_start <= bs < d_end):
            continue
        prof = per.get(r["activity"])
        tot = sum(prof.values()) if prof else 0.0
        if not prof or tot <= 0:
            continue
        for h in hours:
            share = prof.get(h.astimezone(tz).hour, 0.0) / tot
            out[h][r["activity"]] = {"point": r["point"] * share, "lower": r["lower"] * share, "upper": r["upper"] * share,
                                     "activity": r["activity"], "bucket_start": h.isoformat()}
    return out


def _shift_windows(shifts, tz: ZoneInfo) -> list[dict]:
    """Group the day's shifts by (local start hour) into named windows for the heatmap."""
    seen: dict[int, dict] = {}
    for sh, _w in shifts:
        s = _aware(sh.start_at)
        key = s.astimezone(tz).hour
        e = _aware(sh.end_at)
        cur = seen.setdefault(key, {"start": s, "end": e})
        cur["start"], cur["end"] = min(cur["start"], s), max(cur["end"], e)
    out = []
    for hr in sorted(seen):
        out.append({"code": f"{hr:02d}:00", "start": seen[hr]["start"], "end": seen[hr]["end"]})
    return out


def roster_preview(db: Session, tenant_id: str, site: Site, tz: ZoneInfo, now: datetime) -> list[dict]:
    out = []
    for offset, label in ((0, "Today"), (1, "Tomorrow")):
        base = (now.astimezone(tz) + timedelta(days=offset)).date().isoformat()
        s, e, _ = local_day_bounds(tz, base, now)
        comm = _site_shifts(db, tenant_id, site.site_id, s, e, "committed")
        prop = _site_shifts(db, tenant_id, site.site_id, s, e, "proposed")
        act = db.scalar(select(ActionRequest).where(ActionRequest.tenant_id == tenant_id, ActionRequest.site_id == site.site_id,
                                                    ActionRequest.action_type == "publish_roster").order_by(ActionRequest.created_at.desc()).limit(1))
        state = "published" if comm else ("draft" if prop else "none")
        out.append({"label": label, "date": base, "shifts": len(comm) or len(prop), "workers": len({sh.worker_id for sh, _ in (comm or prop)}),
                    "state": state, "approval": (act.status if act else None)})
    return out


def recommendations(db: Session, tenant_id: str, site_id: str, now: datetime) -> list[dict]:
    rows = db.execute(
        select(Recommendation, OptimisationRun).join(OptimisationRun, OptimisationRun.run_id == Recommendation.run_id)
        .join(OptimisationRunSite, OptimisationRunSite.run_id == OptimisationRun.run_id)
        .where(Recommendation.tenant_id == tenant_id, OptimisationRunSite.site_id == site_id, OptimisationRun.run_type == "intraday_reallocation",
               OptimisationRun.status.in_(("completed", "completed_with_warnings")))
        .order_by(OptimisationRun.created_at.desc()).limit(3)).all()
    out = []
    for rec, run in rows:
        res = run.result or {}
        moves = [m for m in res.get("reassignments", []) if m.get("moved")]
        k = res.get("kpis", {})
        out.append({"recommendation_id": rec.recommendation_id, "run_id": run.run_id, "title": f"Move {len(moves)} worker(s) to cover backlog" if moves else "No move needed",
                    "moves": [{"from_zone": m["from_zone"], "to_zone": m["to_zone"]} for m in moves][:6],
                    "impact": {"remaining_backlog": k.get("remaining_backlog"), "coverage_pct": k.get("coverage_pct"), "baseline": run.explanation.get("baseline") if run.explanation else None},
                    "created_at": run.created_at, "expires_at": rec.expires_at,
                    "stale": _aware(rec.expires_at) is not None and _aware(rec.expires_at) < now})
    return out


def exception_view(e: ExceptionCase, now: datetime, can_see_names: bool, db: Session) -> dict:
    name = None
    if e.worker_id:
        if can_see_names:
            p = db.get(WorkerPerson, e.worker_id)
            name = p.display_name if p else None
        label = name or f"Worker …{e.worker_id[-4:]}"
    else:
        label = None
    return {"id": e.id, "kind": e.kind, "severity": e.severity, "state": e.state, "site_id": e.site_id, "worker_id": e.worker_id if can_see_names else None,
            "worker_label": label, "shift_id": e.shift_id, "source_occurred_at": e.source_occurred_at, "detected_at": e.detected_at,
            "age_seconds": int((now - _aware(e.source_occurred_at)).total_seconds()), "detection_lag_seconds": int((_aware(e.detected_at) - _aware(e.source_occurred_at)).total_seconds()),
            "owner_user_id": e.owner_user_id, "resolution": e.resolution, "evidence": e.evidence}




def roster_week(db: Session, tenant_id: str, site: Site, start_iso: str | None, days: int, now: datetime, *, can_see_rates: bool, can_see_names: bool,
                view: str | None = None, version_id: str | None = None) -> dict:
    """Board data + hard-rule validation for the site's roster over `days` local days."""
    from app.models.canonical import Availability, SkillCertification

    tz = ZoneInfo(site.timezone)
    days = max(1, min(days, 14))
    if start_iso is None:
        today = now.astimezone(tz).date()
        start_iso = (today - timedelta(days=today.weekday())).isoformat()
    w_start, _, _ = local_day_bounds(tz, start_iso, now)
    end_date = datetime.fromisoformat(start_iso).date() + timedelta(days=days)
    w_end = datetime(end_date.year, end_date.month, end_date.day, tzinfo=tz).astimezone(timezone.utc)

    all_rows = _site_shifts(db, tenant_id, site.site_id, w_start, w_end, None)
    has_draft = any(sh.status == "proposed" for sh, _ in all_rows)
    view = view if view in ("published", "draft") else ("draft" if has_draft else "published")
    want = "proposed" if view == "draft" else "committed"
    if version_id:
        # A specific roster version: its own rows regardless of status (proposed while in draft/approval, committed once published).
        rows_view = [(sh, w) for sh, w in all_rows if sh.source_ref == version_id]
        view = "draft" if want == "proposed" else view
    else:
        rows_view = [(sh, w) for sh, w in all_rows if sh.status == want]
    rows = all_rows  # totals below need both; validation/board use rows_view
    workers = {w.worker_id: w for w in db.scalars(select(Worker).where(Worker.tenant_id == tenant_id, Worker.home_site == site.site_id, Worker.status == "active"))}
    people = {p.worker_id: p for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == tenant_id, WorkerPerson.worker_id.in_(list(workers) or [""])))} if can_see_names else {}
    skills: dict[str, set[str]] = defaultdict(set)
    for c in db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == tenant_id, SkillCertification.worker_id.in_(list(workers) or [""]))):
        skills[c.worker_id].add(c.skill_code)
    unavailable = defaultdict(list)
    for a in db.scalars(select(Availability).where(Availability.tenant_id == tenant_id, Availability.worker_id.in_(list(workers) or [""]),
                                                   Availability.interval_end > w_start, Availability.interval_start < w_end,
                                                   Availability.status.in_(("unavailable", "leave", "rdo")))):
        unavailable[a.worker_id].append((_aware(a.interval_start), _aware(a.interval_end), a.status))
    rates = _rates(db, tenant_id)
    rules = resolve_policy(db, tenant_id).constraints
    rest_hours, max_week = float(rules["min_rest_hours"]), float(rules["max_weekly_hours"])

    by_worker: dict[str, list] = defaultdict(list)
    for sh, w in rows_view:
        by_worker[sh.worker_id].append(sh)
    conflicts: list[dict] = []
    shift_flags: dict[str, list[str]] = defaultdict(list)

    def flag(sh, kind, detail):
        shift_flags[sh.shift_id].append(kind)
        conflicts.append({"kind": kind, "severity": "hard", "shift_id": sh.shift_id, "worker_id": sh.worker_id if can_see_names else None, "detail": detail})

    for wid, lst in by_worker.items():
        lst.sort(key=lambda x: _aware(x.start_at))
        w = workers.get(wid)
        week_hours = 0.0
        for i, sh in enumerate(lst):
            s, e = _aware(sh.start_at), _aware(sh.end_at)
            week_hours += (e - s).total_seconds() / 3600
            if i > 0:
                prev = lst[i - 1]
                if s < _aware(prev.end_at):
                    flag(sh, "overlap", "Overlaps another shift for the same worker")
                elif (s - _aware(prev.end_at)).total_seconds() / 3600 < rest_hours:
                    flag(sh, "rest", f"Less than {rest_hours:g}h rest since previous shift")
            for (us, ue, st) in unavailable.get(wid, []):
                if s < ue and e > us:
                    flag(sh, "availability", f"Worker is {st.replace('_', ' ')} during this shift")
            if sh.role != "general" and sh.role not in skills.get(wid, set()):
                flag(sh, "certification", f"Worker holds no '{sh.role}' skill/certification")
            if w is None or w.home_site != site.site_id:
                flag(sh, "site_eligibility", "Worker is not eligible at this site")
        if week_hours > max_week:
            conflicts.append({"kind": "max_hours", "severity": "hard", "shift_id": lst[-1].shift_id, "worker_id": wid if can_see_names else None,
                              "detail": f"{week_hours:.0f}h scheduled exceeds the {max_week:g}h limit"})
            shift_flags[lst[-1].shift_id].append("max_hours")

    def cost_of(sh, w):
        r = rates.get((w.employment_type, sh.role)) or rates.get((w.employment_type, "general"))
        return None if r is None else r * (_aware(sh.end_at) - _aware(sh.start_at)).total_seconds() / 3600

    def totals(status: str) -> dict:
        sel = [(sh, w) for sh, w in rows if sh.status == status]
        hrs = sum((_aware(sh.end_at) - _aware(sh.start_at)).total_seconds() / 3600 for sh, _ in sel)
        agency = sum((_aware(sh.end_at) - _aware(sh.start_at)).total_seconds() / 3600 for sh, w in sel if w.employment_type == "labour_hire")
        costs = [cost_of(sh, w) for sh, w in sel]
        out = {"shifts": len(sel), "workers": len({sh.worker_id for sh, _ in sel}), "hours": round(hrs, 1),
               "agency_share_pct": round(100 * agency / hrs, 1) if hrs else None}
        if can_see_rates:
            known = [c for c in costs if c is not None]
            out["cost"] = round(sum(known), 2) if sel and len(known) == len(costs) else None
            out["cost_note"] = None if (len(known) == len(costs)) else f"{len(costs) - len(known)} shift(s) have no cost rule; total withheld"
        return out

    # daily coverage band (required vs rostered hours)
    standards = _standards(db, tenant_id, now)
    fc_run, fc_rows = _latest_forecast(db, tenant_id, site.site_id)
    band = []
    for i in range(days):
        d = datetime.fromisoformat(start_iso).date() + timedelta(days=i)
        ds, de, diso = local_day_bounds(tz, d.isoformat(), now)
        req = 0.0
        have = False
        for r in fc_rows:
            bs = datetime.fromisoformat(r["bucket_start"]) if isinstance(r["bucket_start"], str) else r["bucket_start"]
            if ds <= bs < de and r["activity"] in standards:
                req += r["point"] * standards[r["activity"]] / 3600
                have = True
        staffed = sum(min(_aware(sh.end_at), de) .timestamp() / 3600 - max(_aware(sh.start_at), ds).timestamp() / 3600
                      for sh, _ in rows_view if _aware(sh.start_at) < de and _aware(sh.end_at) > ds)
        band.append({"date": diso, "required_hours": round(req, 1) if have else None, "rostered_hours": round(staffed, 1),
                     "status": None if not have else ("covered" if staffed >= req else ("risk" if staffed >= 0.85 * req else "shortage"))})

    act = db.scalar(select(ActionRequest).where(ActionRequest.tenant_id == tenant_id, ActionRequest.site_id == site.site_id,
                                                ActionRequest.action_type == "publish_roster").order_by(ActionRequest.created_at.desc()).limit(1))
    return {
        "site": {"site_id": site.site_id, "name": site.name, "timezone": site.timezone, "operating_mode": site.operating_mode},
        "range": {"start": start_iso, "days": days}, "as_of": now, "view": view, "has_draft": has_draft, "version_id": version_id,
        "workers": [{"worker_id": wid, "label": (people[wid].display_name if wid in people else f"Worker …{wid[-4:]}"), "employment_type": w.employment_type,
                     "skills": sorted(skills.get(wid, set())), "provider_id": w.provider_id} for wid, w in sorted(workers.items(), key=lambda kv: kv[1].employment_type + kv[0])],
        "shifts": [{"shift_id": sh.shift_id, "worker_id": sh.worker_id, "role": sh.role, "zone": sh.zone, "start_at": _aware(sh.start_at), "end_at": _aware(sh.end_at),
                    "status": sh.status, "employment_type": w.employment_type, "break_minutes": 30, "flags": shift_flags.get(sh.shift_id, [])} for sh, w in rows_view],
        "coverage_band": band, "conflicts": conflicts, "hard_conflicts": len(conflicts),
        "totals": {"published": totals("committed"), "draft": totals("proposed")},
        "publication": {"latest_action_status": act.status if act else None, "latest_action_id": act.action_id if act else None,
                        "can_publish": not conflicts},
        "forecast": {"run_id": fc_run.run_id if fc_run else None, "method": f"Daily total: {method_label(fc_run)}"},
        "notes": ["Break length is a nominal 30 min; break rules are not yet configurable.", "Site is derived from the worker's home site."],
    }


def live_attendance(db: Session, tenant_id: str, site: Site, now: datetime, *, can_see_names: bool) -> dict:
    from app.core.exceptions_engine import EARLY_MATCH, LATE_AFTER, NO_SHOW_AFTER

    tz = ZoneInfo(site.timezone)
    sources = site_sources(db, tenant_id, site.site_id, now)
    att = next((s for s in sources if s["key"] == "attendance"), None)
    verified = bool(att and att["fresh"] and att["mode"] in ("live", "simulated"))
    workers = {w.worker_id: w for w in db.scalars(select(Worker).where(Worker.tenant_id == tenant_id, Worker.home_site == site.site_id))}
    win_s, win_e = now - timedelta(hours=12), now + timedelta(hours=3)
    shifts = [sh for sh, _ in _site_shifts(db, tenant_id, site.site_id, win_s, win_e, "committed")]
    sessions = db.scalars(select(AttendanceSession).where(AttendanceSession.tenant_id == tenant_id, AttendanceSession.worker_id.in_(list(workers) or [""]),
                                                          AttendanceSession.start_at > now - timedelta(hours=30))).all()
    people = {p.worker_id: p for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == tenant_id, WorkerPerson.worker_id.in_(list(workers) or [""])))} if can_see_names else {}

    def label(wid):
        return people[wid].display_name if wid in people else f"Worker …{wid[-4:]}"

    rows, matched = [], set()
    for sh in sorted(shifts, key=lambda x: (_aware(x.start_at), x.worker_id)):
        s, e = _aware(sh.start_at), _aware(sh.end_at)
        if not (s - timedelta(hours=1) <= now < e + timedelta(hours=2)):
            continue
        cands = [x for x in sessions if x.worker_id == sh.worker_id and s - EARLY_MATCH <= _aware(x.start_at) < e]
        ss = min(cands, key=lambda x: _aware(x.start_at)) if cands else None
        if ss:
            matched.add(ss.id)
        if now < s:
            state = "upcoming"
        elif ss is None:
            state = ("absent" if now > s + NO_SHOW_AFTER else "awaiting") if verified else "unverified"
        elif ss.end_at is None:
            state = "late" if _aware(ss.start_at) - s > LATE_AFTER else "present"
        else:
            state = "completed"
        rows.append({"shift_id": sh.shift_id, "worker_id": sh.worker_id, "worker_label": label(sh.worker_id), "role": sh.role, "zone": sh.zone,
                     "scheduled_start": s, "scheduled_end": e, "punch_in": _aware(ss.start_at) if ss else None, "punch_out": _aware(ss.end_at) if ss and ss.end_at else None,
                     "state": state, "minutes_late": max(0, int((_aware(ss.start_at) - s).total_seconds() // 60)) if ss else None,
                     "approval": ss.approval if ss else None, "attendance_session_id": ss.id if ss else None})
    unrostered = [x for x in sessions if x.id not in matched and x.end_at is None and _aware(x.start_at) > now - timedelta(hours=12)
                  and not any(sh.worker_id == x.worker_id and _aware(sh.start_at) - EARLY_MATCH <= _aware(x.start_at) < _aware(sh.end_at) for sh in shifts)]
    for x in unrostered:
        rows.append({"shift_id": None, "worker_id": x.worker_id, "worker_label": label(x.worker_id), "role": None, "zone": None, "scheduled_start": None, "scheduled_end": None,
                     "punch_in": _aware(x.start_at), "punch_out": None, "state": "unrostered", "minutes_late": None, "approval": x.approval, "attendance_session_id": x.id})

    active = [r for r in rows if r["state"] in ("present", "late", "absent", "awaiting", "unverified") and r["scheduled_start"] and r["scheduled_start"] <= now]
    counts = {
        "expected": len(active) if active else 0,
        "present": sum(1 for r in rows if r["state"] in ("present", "late")) if verified else None,
        "late": sum(1 for r in rows if r["state"] == "late") if verified else None,
        "absent": sum(1 for r in rows if r["state"] == "absent") if verified else None,
        "unrostered": len(unrostered) if verified else None,
    }
    defs = {"expected": "Rostered workers whose shift has started and not ended.", "present": "Expected workers with an open attendance session.",
            "late": f"Present, but clocked in more than {int(LATE_AFTER.total_seconds() // 60)} min after shift start.",
            "absent": f"Expected, no clock-in {int(NO_SHOW_AFTER.total_seconds() // 60)} min after start.",
            "unrostered": "Open attendance sessions with no matching rostered shift."}
    exc = db.scalars(select(ExceptionCase).where(ExceptionCase.tenant_id == tenant_id, ExceptionCase.site_id == site.site_id).order_by(ExceptionCase.detected_at.desc()).limit(60)).all()
    open_first = sorted(exc, key=lambda e: (e.state not in STATUS_OPEN, {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(e.severity, 9), -_aware(e.detected_at).timestamp()))
    return {"site": {"site_id": site.site_id, "name": site.name, "timezone": site.timezone, "operating_mode": site.operating_mode, "local_now": now.astimezone(tz).isoformat()},
            "as_of": now, "attendance_verified": verified, "data_sources": sources, "counts": counts, "definitions": defs, "rows": rows,
            "exceptions": [exception_view(e, now, can_see_names, db) for e in open_first],
            "stale_message": None if verified else "Attendance is not verified live for this site. Counts that depend on it are withheld — do not read this as 'everyone is present'."}
