"""A customer-supplied forecast, shaped for the planner. Used only when the site's forecast source is 'supplied', and only for activities the
supplied forecast covers completely; anything else falls back to Tempo's model, and the run says so."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imports import SiteForecastPreference, SuppliedForecast


def wants_supplied(db: Session, tenant_id: str, site_ids: list[str]) -> bool:
    if len(site_ids) != 1:
        return False
    p = db.get(SiteForecastPreference, (tenant_id, site_ids[0]))
    return p is not None and p.source == "supplied"


def for_window(db: Session, tenant_id: str, site_id: str, start: datetime, bucket: timedelta, buckets: int, tz: ZoneInfo) -> tuple[dict[str, list[dict]], list[str], list[str]]:
    """(activity → forecast rows, versions used, notes). Matches by site-local date for daily windows."""
    minutes = int(bucket.total_seconds() // 60)
    lo, hi = start - timedelta(days=2), start + bucket * buckets + timedelta(days=2)
    rows = list(db.scalars(select(SuppliedForecast).where(SuppliedForecast.tenant_id == tenant_id, SuppliedForecast.site_id == site_id, SuppliedForecast.state == "active",
                                                          SuppliedForecast.bucket_start >= lo, SuppliedForecast.bucket_start < hi).order_by(SuppliedForecast.created_at)))
    notes: list[str] = []
    if not rows:
        return {}, [], ["no customer-supplied forecast covers this window — Tempo's own forecast is used"]
    if minutes not in (60, 1440):
        return {}, [], ["supplied forecasts support hourly and daily planning windows only — Tempo's own forecast is used"]
    latest: dict[tuple[str, datetime | object], SuppliedForecast] = {}
    for r in rows:  # oldest first, so the newest version of a period wins
        st = r.bucket_start if r.bucket_start.tzinfo else r.bucket_start.replace(tzinfo=timezone.utc)
        if minutes == 1440:
            key = (r.activity, st.astimezone(tz).date())
            if r.bucket_minutes == 60:
                continue
        else:
            if r.bucket_minutes != 60:
                continue
            key = (r.activity, st)
        latest[key] = r
    hourly_to_day: dict[tuple[str, object], float] = defaultdict(float)
    hourly_n: dict[tuple[str, object], int] = defaultdict(int)
    if minutes == 1440:
        newest_h: dict[tuple[str, datetime], SuppliedForecast] = {}
        for r in rows:
            if r.bucket_minutes == 60:
                st = r.bucket_start if r.bucket_start.tzinfo else r.bucket_start.replace(tzinfo=timezone.utc)
                newest_h[(r.activity, st)] = r
        for (act, st), r in newest_h.items():
            k = (act, st.astimezone(tz).date())
            hourly_to_day[k] += r.units
            hourly_n[k] += 1
    out: dict[str, list[dict]] = {}
    versions: set[str] = set()
    acts = {r.activity for r in rows}
    for act in sorted(acts):
        series, ok = [], True
        for k in range(buckets):
            t = start + bucket * k
            key = (act, (t + timedelta(hours=12)).astimezone(tz).date()) if minutes == 1440 else (act, t)
            r = latest.get(key)
            if r is not None:
                series.append({"activity": act, "bucket_start": t.isoformat(), "point": round(r.units, 2), "lower": round(r.lower if r.lower is not None else r.units, 2),
                               "upper": round(r.upper if r.upper is not None else r.units, 2), "origin": f"supplied:{r.version}"})
                versions.add(r.version)
            elif minutes == 1440 and hourly_n.get(key, 0) >= 20:
                series.append({"activity": act, "bucket_start": t.isoformat(), "point": round(hourly_to_day[key], 2), "lower": round(hourly_to_day[key], 2), "upper": round(hourly_to_day[key], 2),
                               "origin": "supplied:hourly-summed"})
            else:
                ok = False
                break
        if ok:
            out[act] = series
        else:
            notes.append(f"the supplied forecast does not cover every period for {act} — Tempo's own forecast is used for it")
    return out, sorted(versions), notes
