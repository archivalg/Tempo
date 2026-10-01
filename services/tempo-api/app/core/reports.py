"""Variance, timesheet and demand read models.

Definitions (versioned in METRIC_DEFS): every figure says whether it is an *estimate* (from unapproved attendance)
or *confirmed* (approved attendance, including approved supervised adjustments). Nothing is invented: a value with
no verified input is `None` with a reason.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import overrides
from app.core.exceptions_engine import EARLY_MATCH, LATE_AFTER, NO_SHOW_AFTER
from app.core.opsview import method_label, _aware, _latest_forecast, _rates, _standards, local_day_bounds, site_sources
from app.models.canonical import ActivityRoleZoneMap, AttendanceSession, DemandBucket, ShiftAssignment, Worker, WorkStandard
from app.models.directory import Site, WorkerPerson
from app.models.rosters import AttendanceAdjustment, DemandOverride

REPORT_VERSION = "tempo-metrics-1.0"
METRIC_DEFS = {
    "scheduled_hours": "Σ hours of published (committed) shifts, to date (up to now for today).",
    "attended_hours": "Σ hours between clock-in and clock-out (open sessions run to now). ESTIMATE until approved.",
    "payable_hours": "Attended hours of APPROVED timesheets, using an approved supervised adjustment where one exists. CONFIRMED.",
    "variance_hours": "attended_hours − scheduled_hours (to date).",
    "adherence": "Matched attended shifts ÷ shifts due (started ≥ 20 min ago). Withheld when attendance is not verified live.",
    "planned_cost": "Σ scheduled hours × the matching cost rule's rate.",
    "estimated_actual_cost": "Σ attended hours × rate. An estimate — attendance may still change.",
    "confirmed_cost": "Σ payable hours × rate. Confirmed.",
    "forecast_wape": "Σ|forecast − actual| ÷ Σ actual over completed days; forecast is the Holt-linear daily total.",
    "productivity": "Units received ÷ attended hours (all attended time is treated as productive; no exclusion policy is configured yet).",
}


def _hours(a: datetime, b: datetime) -> float:
    return max(0.0, (b - a).total_seconds() / 3600)


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> float:
    return _hours(max(a0, b0), min(a1, b1))


def effective_times(session: AttendanceSession, adj: AttendanceAdjustment | None, now: datetime) -> tuple[datetime, datetime]:
    if adj is not None and adj.state == "approved":
        return _aware(adj.requested_start), _aware(adj.requested_end) if adj.requested_end else now
    return _aware(session.start_at), (_aware(session.end_at) if session.end_at else now)


def variance(db: Session, tenant_id: str, site: Site, start_iso: str, days: int, now: datetime, *, can_rates: bool) -> dict:
    tz = ZoneInfo(site.timezone)
    days = max(1, min(days, 14))
    ds = [(datetime.fromisoformat(start_iso).date() + timedelta(days=i)).isoformat() for i in range(days)]
    w_start = local_day_bounds(tz, ds[0], now)[0]
    w_end = local_day_bounds(tz, ds[-1], now)[1]
    workers = {w.worker_id: w for w in db.scalars(select(Worker).where(Worker.tenant_id == tenant_id, Worker.home_site == site.site_id))}
    wids = list(workers) or [""]
    shifts = list(db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == tenant_id, ShiftAssignment.worker_id.in_(wids), ShiftAssignment.status == "committed",
                                                           ShiftAssignment.end_at > w_start, ShiftAssignment.start_at < w_end)))
    sessions = list(db.scalars(select(AttendanceSession).where(AttendanceSession.tenant_id == tenant_id, AttendanceSession.worker_id.in_(wids),
                                                               AttendanceSession.start_at < w_end, (AttendanceSession.end_at.is_(None)) | (AttendanceSession.end_at > w_start))))
    adj = {a.session_id: a for a in db.scalars(select(AttendanceAdjustment).where(AttendanceAdjustment.tenant_id == tenant_id, AttendanceAdjustment.site_id == site.site_id,
                                                                                   AttendanceAdjustment.state == "approved"))}
    rates = _rates(db, tenant_id)
    sources = site_sources(db, tenant_id, site.site_id, now)
    att = next((s for s in sources if s["key"] == "attendance"), None)
    verified = bool(att and att["fresh"] and att["mode"] in ("live", "simulated"))

    def rate_for(wid: str, role: str | None) -> float | None:
        w = workers.get(wid)
        if w is None:
            return None
        return rates.get((w.employment_type, role or "")) or rates.get((w.employment_type, "general"))

    # forecast + actual demand per local day
    fc_run, fc_rows = _latest_forecast(db, tenant_id, site.site_id)
    fc_by_day: dict[str, float] = defaultdict(float)
    for r in fc_rows:
        bs = datetime.fromisoformat(r["bucket_start"]) if isinstance(r["bucket_start"], str) else r["bucket_start"]
        fc_by_day[bs.astimezone(tz).date().isoformat()] += r.get("model_point", r["point"])  # accuracy is measured on the model, before manual overrides
    act_by_day: dict[str, float] = defaultdict(float)
    for b in db.scalars(select(DemandBucket).where(DemandBucket.tenant_id == tenant_id, DemandBucket.site_id == site.site_id, DemandBucket.bucket_minutes == 60,
                                                   DemandBucket.interval_start >= w_start, DemandBucket.interval_start < w_end)):
        act_by_day[_aware(b.interval_start).astimezone(tz).date().isoformat()] += b.volume
    hourly_days = set(act_by_day)
    for b in db.scalars(select(DemandBucket).where(DemandBucket.tenant_id == tenant_id, DemandBucket.site_id == site.site_id, DemandBucket.bucket_minutes == 1440,
                                                   DemandBucket.interval_start >= w_start - timedelta(hours=2), DemandBucket.interval_start < w_end)):
        day = (_aware(b.interval_start) + timedelta(hours=12)).astimezone(tz).date().isoformat()   # daily totals count for days with no hourly data
        if day not in hourly_days:
            act_by_day[day] += b.volume

    rows, missing_rate = [], 0
    for d in ds:
        d0, d1, _ = local_day_bounds(tz, d, now)
        upto = min(d1, now)
        complete = d1 <= now
        sched_to_date = planned_cost = 0.0
        due = matched = late = 0
        overtime = 0.0
        matched_ids: set[str] = set()
        for sh in shifts:
            s, e = _aware(sh.start_at), _aware(sh.end_at)
            if not (s < d1 and e > d0):
                continue
            sched_to_date += _overlap(s, e, d0, upto)
            r = rate_for(sh.worker_id, sh.role)
            if r is None:
                missing_rate += 1
            else:
                planned_cost += r * _overlap(s, e, d0, upto)
            if d0 <= s < d1 and s + NO_SHOW_AFTER <= now:
                due += 1
                cands = [x for x in sessions if x.worker_id == sh.worker_id and s - EARLY_MATCH <= _aware(x.start_at) < e]
                if cands:
                    matched += 1
                    x = min(cands, key=lambda z: _aware(z.start_at))
                    matched_ids.add(x.id)
                    if _aware(x.start_at) - s > LATE_AFTER:
                        late += 1
                    xs, xe = effective_times(x, adj.get(x.id), now)
                    overtime += _hours(e, xe) if xe > e else 0.0
        attended = payable = est_cost = conf_cost = 0.0
        for x in sessions:
            xs, xe = effective_times(x, None, now)
            a = _overlap(xs, xe, d0, upto)
            if a <= 0:
                continue
            attended += a
            r = rate_for(x.worker_id, next((sh.role for sh in shifts if sh.worker_id == x.worker_id), None))
            if r is not None:
                est_cost += r * a
            if x.approval == "approved":
                ps, pe = effective_times(x, adj.get(x.id), now)
                p = _overlap(ps, pe, d0, upto)
                payable += p
                if r is not None:
                    conf_cost += r * p
        f, a_units = fc_by_day.get(d), act_by_day.get(d)
        rows.append({
            "date": d, "complete": complete, "status": "complete" if complete else ("upcoming" if d0 > now else "in_progress"), "scheduled_hours": round(sched_to_date, 1), "attended_hours": round(attended, 1), "payable_hours": round(payable, 1),
            "variance_hours": round(attended - sched_to_date, 1), "shifts_due": due if verified else None, "shifts_matched": matched if verified else None,
            "adherence_pct": (round(100 * matched / due, 1) if due and verified else None), "late": late if verified else None,
            "no_shows": (due - matched) if verified else None, "overtime_hours": round(overtime, 1),
            "forecast_units": None if f is None else round(f), "actual_units": None if not a_units else round(a_units),
            "forecast_ape_pct": (round(100 * abs(f - a_units) / a_units, 1) if (complete and f is not None and a_units) else None),
            "productivity_units_per_hour": (round(a_units / attended, 1) if a_units and attended > 0 and complete else None),
            **({"planned_cost": round(planned_cost, 2), "estimated_actual_cost": round(est_cost, 2), "confirmed_cost": round(conf_cost, 2)} if can_rates else {}),
        })
    tot = lambda k: round(sum(r[k] for r in rows if r.get(k) is not None), 1)  # noqa: E731
    done = [r for r in rows if r["forecast_ape_pct"] is not None]
    wape = None
    if done:
        num = sum(abs(fc_by_day[r["date"]] - act_by_day[r["date"]]) for r in done)
        den = sum(act_by_day[r["date"]] for r in done)
        wape = round(100 * num / den, 1) if den else None
    due_t = sum(r["shifts_due"] or 0 for r in rows)
    totals = {"scheduled_hours": tot("scheduled_hours"), "attended_hours": tot("attended_hours"), "payable_hours": tot("payable_hours"), "variance_hours": tot("variance_hours"),
              "overtime_hours": tot("overtime_hours"), "adherence_pct": (round(100 * sum(r["shifts_matched"] or 0 for r in rows) / due_t, 1) if due_t and verified else None),
              "forecast_wape_pct": wape, "forecast_days_scored": len(done), "unconfirmed_hours": round(tot("attended_hours") - tot("payable_hours"), 1)}
    if can_rates:
        totals.update(planned_cost=tot("planned_cost"), estimated_actual_cost=tot("estimated_actual_cost"), confirmed_cost=tot("confirmed_cost"),
                      cost_variance_estimate=round(tot("estimated_actual_cost") - tot("planned_cost"), 2), missing_rate_count=missing_rate)
    return {"site": {"site_id": site.site_id, "name": site.name, "timezone": site.timezone}, "range": {"start": ds[0], "days": days}, "as_of": now,
            "metric_version": REPORT_VERSION, "definitions": METRIC_DEFS, "attendance_verified": verified, "data_sources": sources, "days": rows, "totals": totals,
            "forecast": {"run_id": fc_run.run_id if fc_run else None, "method": f"{method_label(fc_run)} on daily totals"},
            "labels": {"attended": "estimate", "payable": "confirmed", "planned": "plan"},
            "notes": ["Forecast accuracy is measured on the forecast source in use (Tempo's model or a customer-supplied forecast), before any manual demand override.", "Actual cost is an estimate until timesheets are approved.", "Unrostered hours count in attended hours but have no scheduled counterpart."]}


def timesheets(db: Session, tenant_id: str, site: Site, start_iso: str, days: int, now: datetime, *, can_see_names: bool) -> dict:
    tz = ZoneInfo(site.timezone)
    w_start = local_day_bounds(tz, start_iso, now)[0]
    end_d = datetime.fromisoformat(start_iso).date() + timedelta(days=days)
    w_end = datetime(end_d.year, end_d.month, end_d.day, tzinfo=tz).astimezone(timezone.utc)
    workers = {w.worker_id: w for w in db.scalars(select(Worker).where(Worker.tenant_id == tenant_id, Worker.home_site == site.site_id))}
    people = {p.worker_id: p.display_name for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == tenant_id, WorkerPerson.worker_id.in_(list(workers) or [""])))} if can_see_names else {}
    sessions = list(db.scalars(select(AttendanceSession).where(AttendanceSession.tenant_id == tenant_id, AttendanceSession.worker_id.in_(list(workers) or [""]),
                                                               AttendanceSession.start_at >= w_start, AttendanceSession.start_at < w_end).order_by(AttendanceSession.start_at.desc())))
    shifts = list(db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == tenant_id, ShiftAssignment.worker_id.in_(list(workers) or [""]), ShiftAssignment.status == "committed",
                                                           ShiftAssignment.end_at > w_start - timedelta(hours=12), ShiftAssignment.start_at < w_end)))
    adjs = {}
    for a in db.scalars(select(AttendanceAdjustment).where(AttendanceAdjustment.tenant_id == tenant_id, AttendanceAdjustment.site_id == site.site_id).order_by(AttendanceAdjustment.requested_at)):
        adjs[a.session_id] = a
    out = []
    for x in sessions:
        s = _aware(x.start_at)
        sh = next((h for h in shifts if h.worker_id == x.worker_id and _aware(h.start_at) - EARLY_MATCH <= s < _aware(h.end_at)), None)
        a = adjs.get(x.id)
        es, ee = effective_times(x, a, now)
        out.append({"session_id": x.id, "worker_id": x.worker_id if can_see_names else None, "worker_label": people.get(x.worker_id) or f"Worker …{x.worker_id[-4:]}",
                    "clock_in": s, "clock_out": _aware(x.end_at) if x.end_at else None, "open": x.end_at is None, "approval": x.approval,
                    "scheduled_start": _aware(sh.start_at) if sh else None, "scheduled_end": _aware(sh.end_at) if sh else None, "role": sh.role if sh else None,
                    "matched": sh is not None, "punched_hours": round(_hours(s, _aware(x.end_at) if x.end_at else now), 2),
                    "scheduled_hours": round(_hours(_aware(sh.start_at), _aware(sh.end_at)), 2) if sh else 0.0,
                    "payable_hours": round(_hours(es, ee), 2) if x.approval == "approved" else None,
                    "adjustment": None if a is None else {"id": a.id, "state": a.state, "requested_start": a.requested_start, "requested_end": a.requested_end, "reason": a.reason,
                                                            "requested_by": a.requested_by, "decision_note": a.decision_note}})
    return {"site": {"site_id": site.site_id, "name": site.name, "timezone": site.timezone}, "range": {"start": start_iso, "days": days}, "as_of": now, "sessions": out,
            "summary": {"sessions": len(out), "open": sum(1 for r in out if r["open"]), "approved": sum(1 for r in out if r["approval"] == "approved"),
                        "pending": sum(1 for r in out if r["approval"] != "approved"), "unrostered": sum(1 for r in out if not r["matched"]),
                        "pending_adjustments": sum(1 for r in out if r["adjustment"] and r["adjustment"]["state"] == "pending")}}


def demand(db: Session, tenant_id: str, site: Site, start_iso: str, days: int, now: datetime) -> dict:
    tz = ZoneInfo(site.timezone)
    ds = [(datetime.fromisoformat(start_iso).date() + timedelta(days=i)).isoformat() for i in range(days)]
    w_start, w_end = local_day_bounds(tz, ds[0], now)[0], local_day_bounds(tz, ds[-1], now)[1]
    std = _standards(db, tenant_id, now)
    fc_run, fc_rows = _latest_forecast(db, tenant_id, site.site_id)
    fc: dict[tuple[str, str], dict] = {}
    for r in fc_rows:
        bs = datetime.fromisoformat(r["bucket_start"]) if isinstance(r["bucket_start"], str) else r["bucket_start"]
        fc[(bs.astimezone(tz).date().isoformat(), r["activity"])] = r
    act: dict[tuple[str, str], float] = defaultdict(float)
    for b in db.scalars(select(DemandBucket).where(DemandBucket.tenant_id == tenant_id, DemandBucket.site_id == site.site_id, DemandBucket.bucket_minutes == 60,
                                                   DemandBucket.interval_start >= w_start, DemandBucket.interval_start < w_end)):
        act[(_aware(b.interval_start).astimezone(tz).date().isoformat(), b.activity)] += b.volume
    for b in db.scalars(select(DemandBucket).where(DemandBucket.tenant_id == tenant_id, DemandBucket.site_id == site.site_id, DemandBucket.bucket_minutes == 1440,
                                                   DemandBucket.interval_start >= w_start - timedelta(hours=2), DemandBucket.interval_start < w_end)):
        key = ((_aware(b.interval_start) + timedelta(hours=12)).astimezone(tz).date().isoformat(), b.activity)
        if key not in act:                      # daily totals fill days that have no hourly workload for that activity
            act[key] = b.volume
    activities = sorted({a for _d, a in fc} | {a for _d, a in act} | set(std))
    rows = []
    for d in ds:
        for a in activities:
            f, u = fc.get((d, a)), act.get((d, a))
            req = (f["point"] * std[a] / 3600) if (f and a in std) else None
            rows.append({"date": d, "activity": a, "actual_units": None if u is None else round(u), "forecast_units": None if not f else round(f["point"]), "model_units": None if not f else round(f.get("model_point", f["point"])), "adjusted": bool(f and f.get("override_ids")),
                         "forecast_lower": None if not f else round(f["lower"]), "forecast_upper": None if not f else round(f["upper"]),
                         "seconds_per_unit": std.get(a), "required_hours": None if req is None else round(req, 1)})
    hist_days = db.scalar(select(DemandBucket.interval_start).where(DemandBucket.tenant_id == tenant_id, DemandBucket.site_id == site.site_id, DemandBucket.bucket_minutes == 1440)
                          .order_by(DemandBucket.interval_start).limit(1))
    last_actual = db.scalar(select(DemandBucket.interval_start).where(DemandBucket.tenant_id == tenant_id, DemandBucket.site_id == site.site_id, DemandBucket.bucket_minutes == 60)
                            .order_by(DemandBucket.interval_start.desc()).limit(1))
    zone_map = [{"activity": m.activity, "role": m.role, "zone": m.zone, "weight": m.weight} for m in db.scalars(
        select(ActivityRoleZoneMap).where(ActivityRoleZoneMap.tenant_id == tenant_id, ActivityRoleZoneMap.site_id == site.site_id))]
    standards = [{"activity": w.activity, "seconds_per_unit": w.time_per_unit_seconds, "effective_from": w.effective_from} for w in db.scalars(
        select(WorkStandard).where(WorkStandard.tenant_id == tenant_id).order_by(WorkStandard.activity))]
    sources = site_sources(db, tenant_id, site.site_id, now)
    readiness = [
        {"check": "Demand history", "ok": hist_days is not None, "detail": f"daily history since {hist_days.date().isoformat()}" if hist_days else "no daily history"},
        {"check": "Latest actuals", "ok": last_actual is not None and (now - _aware(last_actual)) < timedelta(hours=6), "detail": f"last hourly actual {_aware(last_actual).astimezone(tz):%d %b %H:%M}" if last_actual else "none"},
        {"check": "Work standards", "ok": all(a in std for a in activities), "detail": f"{len(std)} of {len(activities)} activities have a standard"},
        {"check": "Activity → role/zone map", "ok": bool(zone_map), "detail": f"{len(zone_map)} mappings"},
        {"check": "Forecast", "ok": fc_run is not None, "detail": f"run {fc_run.run_id} at {fc_run.created_at:%d %b %H:%M}" if fc_run else "no forecast run"},
    ]
    return {"site": {"site_id": site.site_id, "name": site.name, "timezone": site.timezone}, "range": {"start": ds[0], "days": days}, "as_of": now, "rows": rows,
            "activities": activities, "standards": standards, "zone_map": zone_map, "readiness": readiness, "data_sources": sources,
            "forecast": {"run_id": fc_run.run_id if fc_run else None, "created_at": fc_run.created_at if fc_run else None, "snapshot_id": fc_run.snapshot_id if fc_run else None,
                         "method": f"{method_label(fc_run)} on daily totals", "backtest_mape": (fc_run.result or {}).get("backtest_mape") if fc_run else None,
                         "confidence": (fc_run.explanation or {}).get("confidence") if fc_run else None,
                         "source": (fc_run.result or {}).get("forecast_source", "generated") if fc_run else None, "supplied_versions": (fc_run.result or {}).get("supplied_versions", []) if fc_run else []},
            "overrides": [overrides.serialise(o, now) for o in db.scalars(select(DemandOverride).where(DemandOverride.tenant_id == tenant_id, DemandOverride.site_id == site.site_id,
                                                                                               DemandOverride.end_date >= ds[0], DemandOverride.start_date <= ds[-1]).order_by(DemandOverride.created_at.desc()))],
            "overrides_note": "Manual adjustments sit on top of the statistical forecast: each needs a reason and an expiry, the model's own number is kept, and accuracy is measured on the model."}
