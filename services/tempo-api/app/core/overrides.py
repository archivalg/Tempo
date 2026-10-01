"""Demand overrides: validation, application to a forecast, and the shape shown to users.

Rules (so an override can never silently distort the plan):
- a reason of substance, an expiry, and a bounded size are mandatory;
- the model's own number is preserved on every adjusted row (`model_point`), and accuracy is measured on it;
- overrides apply only while active and unexpired, and only to single-site forecasts (a multi-site forecast has no site key per row);
- revoking keeps the row: the history of who changed demand, why and when is itself evidence.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rosters import DemandOverride

MULTIPLY_MIN, MULTIPLY_MAX = 0.2, 3.0
MAX_DAYS = 14
MAX_EXPIRY_DAYS = 90
MIN_REASON = 10
APPROVAL_ABOVE = 0.25  # a percentage change beyond ±25 % (or any fixed-units override) needs a second person before it affects the plan


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def validate(mode: str, value: float, start: str, end: str, reason: str, expires_at: datetime, now: datetime) -> str | None:
    """Returns a problem description, or None when the override is acceptable."""
    if mode == "multiply" and not (MULTIPLY_MIN <= value <= MULTIPLY_MAX):
        return f"a percentage change must keep demand between {int(MULTIPLY_MIN * 100)}% and {int(MULTIPLY_MAX * 100)}% of the forecast"
    if mode == "set_units" and not (0 <= value <= 10_000_000):
        return "units must be between 0 and 10,000,000"
    if mode not in ("multiply", "set_units"):
        return "mode must be multiply or set_units"
    if end < start:
        return "the end date is before the start date"
    if (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1 > MAX_DAYS:
        return f"an override can cover at most {MAX_DAYS} days"
    if len(reason.strip()) < MIN_REASON:
        return f"say why in at least {MIN_REASON} characters — the reason is shown to approvers"
    if _aware(expires_at) <= now:
        return "the expiry must be in the future"
    if _aware(expires_at) > now + timedelta(days=MAX_EXPIRY_DAYS):
        return f"an override can last at most {MAX_EXPIRY_DAYS} days before it must be reviewed"
    return None


def needs_approval(mode: str, value: float) -> bool:
    return mode == "set_units" or abs(value - 1.0) > APPROVAL_ABOVE


def active_for(db: Session, tenant_id: str, site_id: str, now: datetime) -> list[DemandOverride]:
    return [o for o in db.scalars(select(DemandOverride).where(DemandOverride.tenant_id == tenant_id, DemandOverride.site_id == site_id,
                                                                 DemandOverride.state == "active").order_by(DemandOverride.created_at))
            if _aware(o.expires_at) > now]


def status_of(o: DemandOverride, now: datetime) -> str:
    if o.state in ("revoked", "rejected", "pending"):
        return o.state
    return "expired" if _aware(o.expires_at) <= now else "active"


def serialise(o: DemandOverride, now: datetime) -> dict:
    return {"id": o.id, "site_id": o.site_id, "activity": o.activity, "start_date": o.start_date, "end_date": o.end_date, "mode": o.mode, "value": o.value,
            "reason": o.reason, "origin": o.origin, "status": status_of(o, now), "expires_at": o.expires_at, "created_by": o.created_by, "created_at": o.created_at,
            "revoked_by": o.revoked_by, "revoked_at": o.revoked_at, "revoke_reason": o.revoke_reason,
            "needs_approval": o.state == "pending", "decided_by": o.decided_by, "decided_at": o.decided_at, "decision_note": o.decision_note}


def apply(rows: list[dict], overrides: list[DemandOverride], tz: ZoneInfo) -> tuple[list[dict], list[str]]:
    """Adjusts forecast rows in place and returns (rows, ids of overrides that changed something)."""
    if not overrides:
        return rows, []
    used: set[str] = set()

    def local_day(r: dict) -> str:
        bs = r["bucket_start"]
        bs = datetime.fromisoformat(bs) if isinstance(bs, str) else bs
        return _aware(bs).astimezone(tz).date().isoformat()

    day_sum: dict[tuple[str, str], float] = defaultdict(float)
    day_n: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        k = (local_day(r), r["activity"])
        day_sum[k] += r["point"]
        day_n[k] += 1
    for r in rows:
        d = local_day(r)
        r.setdefault("model_point", r["point"])
        for o in overrides:
            if not (o.start_date <= d <= o.end_date) or (o.activity and o.activity != r["activity"]):
                continue
            k = (d, r["activity"])
            if o.mode == "multiply":
                f = o.value
                new = r["point"] * f
            else:  # set_units: the day's total for that activity becomes `value`, spread in proportion to the model
                base = day_sum[k]
                new = o.value * (r["point"] / base) if base > 0 else o.value / day_n[k]
                f = new / r["point"] if r["point"] > 0 else 1.0
            lo, hi = r["lower"] * f if r["point"] > 0 else new, r["upper"] * f if r["point"] > 0 else new
            r["point"], r["lower"], r["upper"] = round(new, 2), round(min(lo, new), 2), round(max(hi, new), 2)
            r.setdefault("override_ids", []).append(o.id)
            used.add(o.id)
    return rows, sorted(used)
