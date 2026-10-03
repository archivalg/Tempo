"""Notification jobs for the mobile app: in-app notice + push, reminders, retries, receipts and the optional SMS fallback.

* Lock-screen text is generic. It never carries a site, time, role or person; details appear only inside the app after sign-in.
* A job is unique per (tenant, dedup_key): retries and repeated triggers cannot schedule or send the same thing twice.
* A delivery row stores what the provider answered. Acceptance is not delivery and delivery is not acknowledgement.
* SMS is only ever considered for URGENT jobs, only when the tenant switched it on, the person opted in with a number, the monthly cap allows it,
  and no push was accepted. Nothing is sent when the provider is 'disabled'.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.providers import get_push_provider, get_sms_provider
from app.models.canonical import ShiftAssignment
from app.models.directory import Site
from app.models.mobile import (NotificationJob, NotificationPreference, PushDelivery, PushDevice, SmsUsage, TenantMessaging, WorkerUserLink)
from app.models.rosters import Notification

CATEGORIES = ("roster_published", "shift_changes", "offers", "reminders", "decisions")
LEAD_CHOICES = (15, 30, 60, 120, 240, 720, 1440)
MAX_ATTEMPTS = 3
GENERIC = {   # what a lock screen may show
    "roster_published": ("Roster published", "Open Tempo to see your shifts."),
    "shift_changes": ("Your roster has changed", "Open Tempo for details."),
    "offers": ("New shift offer", "Open Tempo to respond."),
    "reminders": ("Shift reminder", "You have a shift coming up. Open Tempo for details."),
    "decisions": ("Request update", "Open Tempo to see the decision."),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def prefs(db: Session, tenant_id: str, user_id: str) -> NotificationPreference:
    """The user's saved preferences, or an unsaved object holding the defaults."""
    p = db.get(NotificationPreference, (tenant_id, user_id))
    if p is not None:
        return p
    m = db.get(TenantMessaging, tenant_id)
    return NotificationPreference(tenant_id=tenant_id, user_id=user_id, push_enabled=True, roster_published=True, shift_changes=True, offers=True, reminders=True, decisions=True,
                                  reminder_lead_minutes=m.default_reminder_lead_minutes if m else 60, sms_opt_in=False)


def enqueue(db: Session, tenant_id: str, user_id: str, *, kind: str, category: str, dedup_key: str, run_at: datetime, payload: dict, urgent: bool = False,
            notification_id: str | None = None) -> NotificationJob | None:
    """Adds a job unless one with this key already exists (then returns None)."""
    if db.scalar(select(NotificationJob.id).where(NotificationJob.tenant_id == tenant_id, NotificationJob.dedup_key == dedup_key).limit(1)):
        return None
    j = NotificationJob(tenant_id=tenant_id, user_id=user_id, kind=kind, category=category, dedup_key=dedup_key, run_at=run_at, payload=payload, urgent=urgent, notification_id=notification_id)
    db.add(j)
    db.flush()
    return j


def notify_user(db: Session, tenant_id: str, user_ids: list[str], *, category: str, kind: str, title: str, body: str, dedup_key: str, deep_link: str,
                site_id: str | None = None, urgent: bool = False, link: str | None = None) -> int:
    """In-app notice (once per user and key) plus a push job for each newly created notice. `title`/`body` stay in the app; the push is generic."""
    n = 0
    for uid in dict.fromkeys(user_ids):
        if db.scalar(select(Notification.id).where(Notification.tenant_id == tenant_id, Notification.user_id == uid, Notification.dedup_key == dedup_key).limit(1)):
            continue
        note = Notification(tenant_id=tenant_id, user_id=uid, kind=kind, severity="urgent" if urgent else "info", title=title, body=body, link=link or deep_link, site_id=site_id, dedup_key=dedup_key)
        db.add(note)
        db.flush()
        enqueue(db, tenant_id, uid, kind="push", category=category, dedup_key=f"push:{dedup_key}:{uid}", run_at=utcnow(), payload={"deep_link": deep_link}, urgent=urgent, notification_id=note.id)
        n += 1
    return n


def user_for_worker(db: Session, tenant_id: str, worker_id: str) -> str | None:
    return db.scalar(select(WorkerUserLink.user_id).where(WorkerUserLink.tenant_id == tenant_id, WorkerUserLink.worker_id == worker_id))


# ------------------------------------------------------------------------------------------------------------------ sending
def _active_devices(db: Session, tenant_id: str, user_id: str) -> list[PushDevice]:
    return list(db.scalars(select(PushDevice).where(PushDevice.tenant_id == tenant_id, PushDevice.user_id == user_id, PushDevice.revoked_at.is_(None), PushDevice.invalid_at.is_(None))))


def _sms_month_count(db: Session, tenant_id: str, now: datetime) -> int:
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count()).select_from(SmsUsage).where(SmsUsage.tenant_id == tenant_id, SmsUsage.status == "sent", SmsUsage.at >= start)) or 0


def _maybe_sms(db: Session, job: NotificationJob, title: str, now: datetime) -> None:
    tm = db.get(TenantMessaging, job.tenant_id)
    p = prefs(db, job.tenant_id, job.user_id)
    if not (job.urgent and tm and tm.sms_enabled and p.sms_opt_in and p.sms_number):
        return
    if tm.sms_monthly_cap <= 0 or _sms_month_count(db, job.tenant_id, now) >= tm.sms_monthly_cap:
        db.add(SmsUsage(tenant_id=job.tenant_id, user_id=job.user_id, notification_id=job.notification_id, provider=get_sms_provider().name, status="blocked_cap", segments=0))
        return
    res = get_sms_provider().send(p.sms_number, f"Tempo: {title}. Open the app for details.")
    if res.status != "not_sent":
        db.add(SmsUsage(tenant_id=job.tenant_id, user_id=job.user_id, notification_id=job.notification_id, provider=get_sms_provider().name, status=res.status, segments=res.segments))


def process_job(db: Session, job: NotificationJob, now: datetime | None = None) -> str:
    """Runs one job; returns its resulting status. Safe to call twice (a finished job is left alone)."""
    now = now or utcnow()
    if job.status != "pending":
        return job.status

    def finish(status: str, why: str | None = None) -> str:
        job.status, job.last_error, job.processed_at = status, why, now
        return status

    tm = db.get(TenantMessaging, job.tenant_id)
    p = prefs(db, job.tenant_id, job.user_id)
    if job.kind == "reminder":
        sh = db.get(ShiftAssignment, job.payload.get("shift_id", ""))
        if sh is None or sh.status != "committed" or aware(sh.start_at).isoformat() != job.payload.get("start_at") or aware(sh.start_at) <= now:
            return finish("cancelled", "the shift changed, was cancelled or has already started")
    if (tm is not None and not tm.push_enabled) or not p.push_enabled or not getattr(p, job.category, True):
        return finish("skipped", "turned off in notification settings")
    devices = _active_devices(db, job.tenant_id, job.user_id)
    title, body = GENERIC[job.category]
    prov = get_push_provider()
    data = {"deep_link": job.payload.get("deep_link"), "notification_id": job.notification_id, "job_id": job.id}
    job.attempts += 1
    accepted, retryable = 0, False
    for d in devices:
        r = prov.send(d.token, title, body, data)
        db.add(PushDelivery(tenant_id=job.tenant_id, job_id=job.id, notification_id=job.notification_id, device_id=d.id, status=("failed" if r.status == "not_sent" else r.status), provider=prov.name,
                            provider_ref=r.provider_ref, error=r.error, attempted_at=now))
        if r.status == "accepted":
            accepted += 1
        elif r.status == "device_unregistered":
            d.invalid_at, d.invalid_reason = now, "provider reported the device is no longer registered"
        elif r.status in ("failed",):
            retryable = True
    if accepted == 0:
        _maybe_sms(db, job, job.payload.get("sms_title") or title, now)
    if accepted:
        return finish("done")
    if not devices:
        return finish("skipped", "no registered device")
    if prov.name == "disabled":
        return finish("skipped", "push provider is not configured")
    if retryable and job.attempts < MAX_ATTEMPTS:
        job.run_at, job.last_error = now + timedelta(minutes=2 ** job.attempts), "provider failure; will retry"
        return "pending"
    return finish("failed", "no device accepted the notification")


def check_receipts(db: Session, tenant_id: str, now: datetime | None = None) -> int:
    """Asks the provider what happened to messages it accepted at least 15 minutes ago. A receipt is the provider's word, not the person's."""
    now = now or utcnow()
    rows = list(db.scalars(select(PushDelivery).where(PushDelivery.tenant_id == tenant_id, PushDelivery.status == "accepted", PushDelivery.provider_ref.is_not(None),
                                                      PushDelivery.receipt_checked_at.is_(None), PushDelivery.attempted_at <= now - timedelta(minutes=15)).limit(200)))
    if not rows:
        return 0
    got = get_push_provider().receipts([r.provider_ref for r in rows if r.provider_ref])
    n = 0
    for r in rows:
        if r.provider_ref in got:
            status, detail = got[r.provider_ref]
            r.receipt_status, r.receipt_checked_at = status, now
            if status != "ok":
                r.error = detail
                if detail == "DeviceNotRegistered":
                    d = db.get(PushDevice, r.device_id)
                    if d is not None and d.invalid_at is None:
                        d.invalid_at, d.invalid_reason = now, "provider receipt: device no longer registered"
            n += 1
    return n


def schedule_reminders(db: Session, tenant_id: str, now: datetime | None = None, horizon_hours: int = 48) -> int:
    """Creates a reminder job for each linked employee's upcoming published shift, at their chosen lead time. Idempotent: a shift and start time
    get one job per lead; a changed start time gets a new job and the old one cancels itself when it runs."""
    now = now or utcnow()
    links = {x.worker_id: x.user_id for x in db.scalars(select(WorkerUserLink).where(WorkerUserLink.tenant_id == tenant_id))}
    if not links:
        return 0
    shifts = db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == tenant_id, ShiftAssignment.worker_id.in_(list(links)), ShiftAssignment.status == "committed",
                                                       ShiftAssignment.start_at > now, ShiftAssignment.start_at <= now + timedelta(hours=horizon_hours)))
    n = 0
    for sh in shifts:
        uid = links[sh.worker_id]
        p = prefs(db, tenant_id, uid)
        if not p.reminders:
            continue
        start = aware(sh.start_at)
        run_at = start - timedelta(minutes=p.reminder_lead_minutes)
        if run_at <= now - timedelta(minutes=5):
            continue   # too late to be a useful reminder; never send a stale one
        key = f"reminder:{sh.shift_id}:{start.isoformat()}:{p.reminder_lead_minutes}:{uid}"
        if enqueue(db, tenant_id, uid, kind="reminder", category="reminders", dedup_key=key, run_at=max(run_at, now), payload={"shift_id": sh.shift_id, "start_at": start.isoformat(), "deep_link": f"tempo://shifts/{sh.shift_id}"}):
            n += 1
    return n


def process_due(db: Session, tenant_id: str, now: datetime | None = None, limit: int = 200) -> dict:
    now = now or utcnow()
    scheduled = schedule_reminders(db, tenant_id, now)
    jobs = list(db.scalars(select(NotificationJob).where(NotificationJob.tenant_id == tenant_id, NotificationJob.status == "pending", NotificationJob.run_at <= now).order_by(NotificationJob.run_at).limit(limit)))
    out: dict[str, int] = {}
    for j in jobs:
        st = process_job(db, j, now)
        out[st] = out.get(st, 0) + 1
    receipts = check_receipts(db, tenant_id, now)
    return {"scheduled": scheduled, "processed": len(jobs), "results": out, "receipts_checked": receipts}
