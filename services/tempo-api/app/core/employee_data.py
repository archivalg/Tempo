"""What an employee may see, and how a published roster change is turned into 'what changed for me'.

Visibility rule: an employee sees only COMMITTED (published) shifts of their own worker record. Drafts, submitted and approved-but-unpublished rosters
are stored as 'proposed' rows and are never returned here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import push
from app.models.canonical import ShiftAssignment, Worker
from app.models.directory import Site
from app.models.mobile import ShiftChangeEvent, ShiftOfferRecipient

SOON = timedelta(hours=24)


def aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def visible_shifts(db: Session, tenant_id: str, worker_id: str, start: datetime, end: datetime) -> list[ShiftAssignment]:
    return list(db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == tenant_id, ShiftAssignment.worker_id == worker_id, ShiftAssignment.status == "committed",
                                                         ShiftAssignment.end_at > start, ShiftAssignment.start_at < end).order_by(ShiftAssignment.start_at)))


def shift_view(sh: ShiftAssignment, site: Site, reconfirm: bool = False) -> dict:
    tz = ZoneInfo(site.timezone)
    s, e = aware(sh.start_at), aware(sh.end_at)
    ls, le = s.astimezone(tz), e.astimezone(tz)
    return {"id": sh.shift_id, "site_id": site.site_id, "site_name": site.name, "timezone": site.timezone, "role": sh.role, "zone": sh.zone,
            "start_at": s.isoformat(), "end_at": e.isoformat(), "start_local": ls.isoformat(), "end_local": le.isoformat(), "local_date": ls.date().isoformat(),
            "overnight": le.date() != ls.date(), "duration_minutes": int((e - s).total_seconds() // 60), "dst_change_during_shift": ls.utcoffset() != le.utcoffset(),
            "break_minutes": sh.break_minutes, "instructions": sh.instructions, "status": "needs_reconfirmation" if reconfirm else "scheduled"}


def reconfirm_ids(db: Session, tenant_id: str, worker_id: str) -> set[str]:
    """Shifts created from an accepted offer that was changed afterwards: the employee must confirm again."""
    out = set()
    for r in db.scalars(select(ShiftOfferRecipient).where(ShiftOfferRecipient.tenant_id == tenant_id, ShiftOfferRecipient.worker_id == worker_id, ShiftOfferRecipient.response == "needs_reconfirmation")):
        out.add(r.offer_id)
    return out


# ------------------------------------------------------------------------------------------------------------------ publish diff
def snapshot(rows: list[ShiftAssignment]) -> list[dict]:
    return [{"id": r.shift_id, "worker_id": r.worker_id, "role": r.role, "zone": r.zone, "start_at": aware(r.start_at), "end_at": aware(r.end_at), "break_minutes": r.break_minutes, "instructions": r.instructions} for r in rows]


def _brief(x: dict) -> dict:
    return {"role": x["role"], "zone": x["zone"], "start_at": x["start_at"].isoformat(), "end_at": x["end_at"].isoformat(), "break_minutes": x["break_minutes"], "instructions": x["instructions"]}


def pair_changes(old: list[dict], new: list[dict], tz: ZoneInfo) -> list[tuple[str, dict | None, dict | None]]:
    """Per worker: ('added'|'changed'|'cancelled', before, after). Identical shifts produce nothing."""
    old, new = list(old), list(new)
    same = lambda a, b: all(a[k] == b[k] for k in ("role", "zone", "start_at", "end_at", "break_minutes", "instructions"))  # noqa: E731
    for o in list(old):
        m = next((n for n in new if same(o, n)), None)
        if m is not None:
            old.remove(o)
            new.remove(m)
    out: list[tuple[str, dict | None, dict | None]] = []
    for o in list(old):
        m = next((n for n in new if n["start_at"] == o["start_at"]), None)
        if m is not None:
            out.append(("changed", o, m)); old.remove(o); new.remove(m)
    for o in list(old):
        day = o["start_at"].astimezone(tz).date()
        same_day_old = [x for x in old if x["start_at"].astimezone(tz).date() == day]
        same_day_new = [x for x in new if x["start_at"].astimezone(tz).date() == day]
        if len(same_day_old) == 1 and len(same_day_new) == 1:
            out.append(("changed", o, same_day_new[0])); old.remove(o); new.remove(same_day_new[0])
    out += [("cancelled", o, None) for o in old] + [("added", None, n) for n in new]
    return out


def record_publish_changes(db: Session, tenant_id: str, site: Site, week_start: str, version_id: str, before: list[dict], after: list[dict], now: datetime | None = None) -> dict:
    """Writes one ShiftChangeEvent per changed shift and notifies each affected linked employee once per roster version."""
    now = now or push.utcnow()
    tz = ZoneInfo(site.timezone)
    workers = {x["worker_id"] for x in before} | {x["worker_id"] for x in after}
    notified = events = 0
    for wid in sorted(workers):
        o = [x for x in before if x["worker_id"] == wid]
        n = [x for x in after if x["worker_id"] == wid]
        changes = pair_changes(o, n, tz)
        if not changes:
            continue
        urgent = False
        for kind, b, a in changes:
            ref = a or b
            db.add(ShiftChangeEvent(tenant_id=tenant_id, site_id=site.site_id, worker_id=wid, shift_id=(a or b)["id"], kind=kind, before=_brief(b) if b else None, after=_brief(a) if a else None, source_ref=version_id, at=now))
            events += 1
            if kind != "added" and ref["start_at"] - now <= SOON and ref["end_at"] > now:
                urgent = True
        uid = push.user_for_worker(db, tenant_id, wid)
        if uid is None:
            continue
        first = not o
        counts = {k: sum(1 for c in changes if c[0] == k) for k in ("added", "changed", "cancelled")}
        if first:
            notified += push.notify_user(db, tenant_id, [uid], category="roster_published", kind="roster.published_to_me", title=f"Your roster for the week of {week_start} is published",
                                         body=f"{counts['added']} shift(s).", dedup_key=f"roster_published:{version_id}:{wid}", deep_link="tempo://shifts", site_id=site.site_id)
        else:
            parts = [f"{counts[k]} {k}" for k in ("changed", "cancelled", "added") if counts[k]]
            notified += push.notify_user(db, tenant_id, [uid], category="shift_changes", kind="roster.changed_for_me", title="Your roster has changed", body=", ".join(parts) + ".",
                                         dedup_key=f"shift_changes:{version_id}:{wid}", deep_link="tempo://changes", site_id=site.site_id, urgent=urgent)
    return {"events": events, "notified": notified}
