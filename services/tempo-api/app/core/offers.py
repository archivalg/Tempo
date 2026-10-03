"""Shift offers: a manager offers a shift to chosen employees; the first acceptance holds it; the manager confirms (or it auto-confirms when nothing conflicts).

What happens to an acceptance when the shift is changed afterwards (decided and tested):
* offer still open or awaiting confirmation: the accepted response is VOIDED; the offer reopens and the person is told the offer changed;
* offer filled (a real shift exists): the shift is updated, the person's acceptance becomes 'needs_reconfirmation', they are told (urgent if it starts within 24 h),
  and the shift stays on their roster, flagged, until they confirm again. If they decline instead, the shift is cancelled and managers are alerted urgently.
* offer cancelled after acceptance: the shift is cancelled and the person is told.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import push
from app.core.notifications import recipients as manager_recipients
from app.core.policy import resolve_policy
from app.errors import PolicyConflict, RunNotFound, ScopeError
from app.models.canonical import Availability, ShiftAssignment, Worker
from app.models.directory import Site
from app.models.mobile import ShiftChangeEvent, ShiftOffer, ShiftOfferRecipient

SOON = timedelta(hours=24)
UNAVAILABLE = ("unavailable", "leave", "rdo")


def aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def conflicts(db: Session, tenant_id: str, worker_id: str, start: datetime, end: datetime, exclude_shift: str | None = None) -> list[str]:
    """Reasons this person cannot take this shift (empty = fine). Same rules the roster board enforces: overlap, minimum rest, leave/unavailability."""
    out: list[str] = []
    w = db.get(Worker, worker_id)
    if w is None or w.tenant_id != tenant_id or w.status != "active":
        return ["the person is not active"]
    rest = float(resolve_policy(db, tenant_id).constraints["min_rest_hours"])
    near = db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == tenant_id, ShiftAssignment.worker_id == worker_id, ShiftAssignment.status == "committed",
                                                    ShiftAssignment.end_at > start - timedelta(hours=rest), ShiftAssignment.start_at < end + timedelta(hours=rest)))
    for s in near:
        if s.shift_id == exclude_shift:
            continue
        if aware(s.start_at) < end and aware(s.end_at) > start:
            out.append("overlaps another shift")
        else:
            out.append(f"less than {rest:g} hours rest from another shift")
    for a in db.scalars(select(Availability).where(Availability.tenant_id == tenant_id, Availability.worker_id == worker_id, Availability.status.in_(UNAVAILABLE),
                                                   Availability.interval_start < end, Availability.interval_end > start)):
        out.append("unavailable or on leave")
        break
    return sorted(set(out))


def _site(db: Session, tenant_id: str, site_id: str) -> Site:
    s = db.get(Site, (tenant_id, site_id))
    if s is None:
        raise RunNotFound("site not found")
    return s


def offer_view(db: Session, o: ShiftOffer, *, worker_id: str | None = None, managers: bool = False) -> dict:
    site = _site(db, o.tenant_id, o.site_id)
    tz = ZoneInfo(site.timezone)
    s, e = aware(o.start_at), aware(o.end_at)
    recips = list(db.scalars(select(ShiftOfferRecipient).where(ShiftOfferRecipient.offer_id == o.id).order_by(ShiftOfferRecipient.worker_id)))
    mine = next((r for r in recips if r.worker_id == worker_id), None)
    base = {"id": o.id, "site_id": o.site_id, "site_name": site.name, "timezone": site.timezone, "role": o.role, "zone": o.zone, "start_at": s.isoformat(), "end_at": e.isoformat(),
            "start_local": s.astimezone(tz).isoformat(), "end_local": e.astimezone(tz).isoformat(), "break_minutes": o.break_minutes, "instructions": o.instructions,
            "expires_at": o.expires_at.isoformat() if o.expires_at else None, "status": o.status, "created_at": o.created_at.isoformat()}
    if managers:
        base.update({"auto_confirm": o.auto_confirm, "accepted_worker_id": o.accepted_worker_id, "assignment_id": o.assignment_id, "decision_note": o.decision_note,
                     "recipients": [{"worker_id": r.worker_id, "response": r.response, "responded_at": r.responded_at.isoformat() if r.responded_at else None, "note": r.note} for r in recips]})
    if mine is not None:
        base["my_response"] = mine.response
        base["shift_id"] = o.assignment_id if o.accepted_worker_id == worker_id and o.status == "filled" else None
        taken = o.status in ("filled", "pending_confirmation") and o.accepted_worker_id != worker_id
        base["status_for_me"] = ("taken" if taken else "expired" if o.status == "expired" else "cancelled" if o.status == "cancelled" else mine.response if mine.response != "pending" else "open")
    return base


def _notify_managers(db: Session, o: ShiftOffer, title: str, body: str, key: str, urgent: bool = False) -> None:
    uids = manager_recipients(db, o.tenant_id, o.site_id, "labour.plan")
    push.notify_user(db, o.tenant_id, uids, category="decisions", kind="offer.update", title=title, body=body, dedup_key=key, deep_link="/offers", site_id=o.site_id, urgent=urgent, link="/offers")


def _tell(db: Session, o: ShiftOffer, worker_id: str, category: str, kind: str, title: str, body: str, key: str, deep: str, urgent: bool = False) -> None:
    uid = push.user_for_worker(db, o.tenant_id, worker_id)
    if uid:
        push.notify_user(db, o.tenant_id, [uid], category=category, kind=kind, title=title, body=body, dedup_key=key, deep_link=deep, site_id=o.site_id, urgent=urgent)


def create_offer(db: Session, tenant_id: str, site_id: str, actor: str, *, role: str, zone: str, start_at: datetime, end_at: datetime, worker_ids: list[str], break_minutes: int | None,
                 instructions: str | None, expires_at: datetime | None, auto_confirm: bool, now: datetime | None = None) -> ShiftOffer:
    now = now or push.utcnow()
    site = _site(db, tenant_id, site_id)
    if end_at <= start_at or end_at - start_at > timedelta(hours=16):
        raise ScopeError("a shift must end after it starts and be at most 16 hours")
    if start_at <= now:
        raise ScopeError("an offer must be for a future shift")
    if expires_at is not None and expires_at >= start_at:
        raise ScopeError("an offer must expire before the shift starts")
    ids = list(dict.fromkeys(worker_ids))
    if not ids:
        raise ScopeError("choose at least one person to offer the shift to")
    bad = []
    for wid in ids:
        w = db.get(Worker, wid)
        if w is None or w.tenant_id != tenant_id or w.home_site != site_id or w.status != "active":
            raise ScopeError(f"'{wid}' is not an active person at this site")
        if push.user_for_worker(db, tenant_id, wid) is None:
            bad.append(wid)
    if bad:
        raise ScopeError("these people have not joined the Tempo app, so they cannot receive an offer: " + ", ".join(bad))
    o = ShiftOffer(tenant_id=tenant_id, site_id=site_id, role=role, zone=zone, start_at=start_at, end_at=end_at, break_minutes=break_minutes, instructions=instructions, expires_at=expires_at,
                   auto_confirm=auto_confirm, created_by=actor, status="open")
    db.add(o)
    db.flush()
    for wid in ids:
        db.add(ShiftOfferRecipient(offer_id=o.id, worker_id=wid, tenant_id=tenant_id, site_id=site_id, response="pending"))
        _tell(db, o, wid, "offers", "offer.new", "New shift offer", f"{role} on {start_at.astimezone(ZoneInfo(site.timezone)).strftime('%a %d %b %H:%M')}.", f"offer:{o.id}:new", f"tempo://offers/{o.id}", urgent=(start_at - now) <= SOON)
    return o


def _lock(db: Session, offer_id: str, tenant_id: str) -> ShiftOffer:
    o = db.scalar(select(ShiftOffer).where(ShiftOffer.id == offer_id, ShiftOffer.tenant_id == tenant_id).with_for_update())
    if o is None:
        raise RunNotFound("offer not found")
    return o


def _expire_if_due(o: ShiftOffer, now: datetime) -> None:
    if o.status in ("open", "pending_confirmation") and ((o.expires_at and aware(o.expires_at) <= now) or aware(o.start_at) <= now):
        o.status = "expired"


def _fill(db: Session, o: ShiftOffer, worker_id: str, actor: str, now: datetime) -> None:
    problems = conflicts(db, o.tenant_id, worker_id, aware(o.start_at), aware(o.end_at))
    if problems:
        raise PolicyConflict("this shift cannot be confirmed: " + "; ".join(problems))
    sh = ShiftAssignment(tenant_id=o.tenant_id, worker_id=worker_id, role=o.role, zone=o.zone, start_at=o.start_at, end_at=o.end_at, status="committed", source_system="tempo_native",
                         source_ref=f"offer:{o.id}", break_minutes=o.break_minutes, instructions=o.instructions)
    db.add(sh)
    db.flush()
    o.status, o.assignment_id, o.accepted_worker_id, o.decided_by, o.decided_at = "filled", sh.shift_id, worker_id, actor, now
    db.add(ShiftChangeEvent(tenant_id=o.tenant_id, site_id=o.site_id, worker_id=worker_id, shift_id=sh.shift_id, kind="added", before=None,
                            after={"role": o.role, "zone": o.zone, "start_at": aware(o.start_at).isoformat(), "end_at": aware(o.end_at).isoformat(), "break_minutes": o.break_minutes, "instructions": o.instructions},
                            source_ref=f"offer:{o.id}", at=now))
    for r in db.scalars(select(ShiftOfferRecipient).where(ShiftOfferRecipient.offer_id == o.id, ShiftOfferRecipient.worker_id != worker_id)):
        if r.response in ("pending", "declined"):
            r.response = "not_taken" if r.response == "pending" else r.response
    _tell(db, o, worker_id, "decisions", "offer.confirmed", "Shift confirmed", "Your shift is on your roster.", f"offer:{o.id}:confirmed", f"tempo://shifts/{sh.shift_id}")


def respond(db: Session, tenant_id: str, offer_id: str, worker: Worker, action: str, note: str | None = None, now: datetime | None = None) -> ShiftOffer:
    """accept | decline by the employee. Server-validated; repeating the same answer changes nothing."""
    now = now or push.utcnow()
    o = _lock(db, offer_id, tenant_id)
    r = db.get(ShiftOfferRecipient, (offer_id, worker.worker_id))
    if r is None:
        raise RunNotFound("offer not found")
    _expire_if_due(o, now)
    if o.status == "filled" and o.accepted_worker_id == worker.worker_id and r.response == "needs_reconfirmation":
        if action == "accept":
            r.response, r.responded_at, r.note = "accepted", now, note
            _notify_managers(db, o, "Offer reconfirmed", "The employee reconfirmed the changed shift.", f"offer:{o.id}:reconfirmed:{now.isoformat()}")
        else:
            r.response, r.responded_at, r.note = "declined", now, note
            sh = db.get(ShiftAssignment, o.assignment_id)
            if sh is not None and sh.status == "committed":
                sh.status = "cancelled"
                db.add(ShiftChangeEvent(tenant_id=tenant_id, site_id=o.site_id, worker_id=worker.worker_id, shift_id=sh.shift_id, kind="cancelled",
                                        before={"role": sh.role, "zone": sh.zone, "start_at": aware(sh.start_at).isoformat(), "end_at": aware(sh.end_at).isoformat()}, after=None, source_ref=f"offer:{o.id}", at=now))
            o.status, o.decision_note = "cancelled", "declined after the shift was changed"
            _notify_managers(db, o, "Shift declined after a change", "An employee declined a shift you changed; it is uncovered.", f"offer:{o.id}:declined-after-change", urgent=True)
        return o
    if r.response == ("accepted" if action == "accept" else "declined") and o.status != "expired":
        return o   # repeat of the same answer
    if o.status == "expired":
        raise PolicyConflict("this offer has expired")
    if o.status == "cancelled":
        raise PolicyConflict("this offer was cancelled")
    if action == "accept":
        if o.status != "open":
            raise PolicyConflict("this shift has already been taken")
        problems = conflicts(db, tenant_id, worker.worker_id, aware(o.start_at), aware(o.end_at))
        if problems:
            raise PolicyConflict("you cannot take this shift: " + "; ".join(problems))
        r.response, r.responded_at, r.note = "accepted", now, note
        o.accepted_worker_id = worker.worker_id
        if o.auto_confirm:
            _fill(db, o, worker.worker_id, "auto", now)
        else:
            o.status = "pending_confirmation"
            _notify_managers(db, o, "Shift offer accepted", "An employee accepted an offer. Confirm it to put it on the roster.", f"offer:{o.id}:accepted:{worker.worker_id}")
    elif action == "decline":
        if o.status == "filled":
            raise PolicyConflict("this shift is already confirmed; ask your manager to change it")
        was_holder = o.accepted_worker_id == worker.worker_id and o.status == "pending_confirmation"
        r.response, r.responded_at, r.note = "declined", now, note
        if was_holder:
            o.status, o.accepted_worker_id = "open", None
        everyone = list(db.scalars(select(ShiftOfferRecipient.response).where(ShiftOfferRecipient.offer_id == o.id)))
        if all(x == "declined" for x in everyone):
            _notify_managers(db, o, "Shift offer declined by everyone", "No one has taken the offered shift.", f"offer:{o.id}:all-declined")
    else:
        raise ScopeError("action must be accept or decline")
    return o


def confirm(db: Session, tenant_id: str, offer_id: str, actor: str, now: datetime | None = None) -> ShiftOffer:
    now = now or push.utcnow()
    o = _lock(db, offer_id, tenant_id)
    _expire_if_due(o, now)
    if o.status != "pending_confirmation":
        raise PolicyConflict(f"only an accepted offer can be confirmed (this one is {o.status})")
    _fill(db, o, o.accepted_worker_id, actor, now)
    return o


def reject(db: Session, tenant_id: str, offer_id: str, actor: str, note: str, now: datetime | None = None) -> ShiftOffer:
    now = now or push.utcnow()
    o = _lock(db, offer_id, tenant_id)
    if o.status != "pending_confirmation":
        raise PolicyConflict(f"only an accepted offer can be rejected (this one is {o.status})")
    wid = o.accepted_worker_id
    r = db.get(ShiftOfferRecipient, (o.id, wid))
    r.response, r.responded_at = "rejected_by_manager", now
    o.status, o.accepted_worker_id, o.decision_note, o.decided_by, o.decided_at = "open", None, note, actor, now
    _tell(db, o, wid, "decisions", "offer.rejected", "Shift offer not confirmed", "Your manager did not confirm this shift.", f"offer:{o.id}:rejected:{wid}", f"tempo://offers/{o.id}")
    return o


def cancel(db: Session, tenant_id: str, offer_id: str, actor: str, note: str = "", now: datetime | None = None) -> ShiftOffer:
    now = now or push.utcnow()
    o = _lock(db, offer_id, tenant_id)
    if o.status in ("cancelled", "expired"):
        return o
    was_filled = o.status == "filled"
    o.status, o.decision_note, o.decided_by, o.decided_at = "cancelled", note, actor, now
    if was_filled and o.assignment_id:
        sh = db.get(ShiftAssignment, o.assignment_id)
        if sh is not None and sh.status == "committed":
            sh.status = "cancelled"
            db.add(ShiftChangeEvent(tenant_id=tenant_id, site_id=o.site_id, worker_id=sh.worker_id, shift_id=sh.shift_id, kind="cancelled",
                                    before={"role": sh.role, "zone": sh.zone, "start_at": aware(sh.start_at).isoformat(), "end_at": aware(sh.end_at).isoformat()}, after=None, source_ref=f"offer:{o.id}", at=now))
            _tell(db, o, sh.worker_id, "shift_changes", "offer.shift_cancelled", "A shift was cancelled", "Open Tempo for details.", f"offer:{o.id}:shift-cancelled", "tempo://changes", urgent=(aware(sh.start_at) - now) <= SOON)
    else:
        for r in db.scalars(select(ShiftOfferRecipient).where(ShiftOfferRecipient.offer_id == o.id)):
            _tell(db, o, r.worker_id, "offers", "offer.cancelled", "Shift offer withdrawn", "This offer is no longer available.", f"offer:{o.id}:cancelled:{r.worker_id}", f"tempo://offers/{o.id}")
    return o


def edit(db: Session, tenant_id: str, offer_id: str, actor: str, changes: dict, now: datetime | None = None) -> ShiftOffer:
    """Change a shift that was offered. See the module docstring for what this does to an acceptance."""
    now = now or push.utcnow()
    o = _lock(db, offer_id, tenant_id)
    if o.status not in ("open", "pending_confirmation", "filled"):
        raise PolicyConflict(f"a {o.status} offer cannot be changed")
    before = {"role": o.role, "zone": o.zone, "start_at": aware(o.start_at).isoformat(), "end_at": aware(o.end_at).isoformat(), "break_minutes": o.break_minutes, "instructions": o.instructions}
    for k in ("role", "zone", "start_at", "end_at", "break_minutes", "instructions"):
        if k in changes and changes[k] is not None:
            setattr(o, k, changes[k])
    if aware(o.end_at) <= aware(o.start_at) or aware(o.end_at) - aware(o.start_at) > timedelta(hours=16):
        raise ScopeError("a shift must end after it starts and be at most 16 hours")
    after = {"role": o.role, "zone": o.zone, "start_at": aware(o.start_at).isoformat(), "end_at": aware(o.end_at).isoformat(), "break_minutes": o.break_minutes, "instructions": o.instructions}
    if before == after:
        return o
    tag = hashlib.sha1(str(sorted(after.items())).encode()).hexdigest()[:8]   # a different change gets a different notification key
    if o.status == "filled" and o.assignment_id:
        sh = db.get(ShiftAssignment, o.assignment_id)
        wid = o.accepted_worker_id
        problems = conflicts(db, tenant_id, wid, aware(o.start_at), aware(o.end_at), exclude_shift=sh.shift_id)
        if problems:
            raise PolicyConflict("the change would clash for the employee: " + "; ".join(problems))
        sh.role, sh.zone, sh.start_at, sh.end_at, sh.break_minutes, sh.instructions = o.role, o.zone, o.start_at, o.end_at, o.break_minutes, o.instructions
        r = db.get(ShiftOfferRecipient, (o.id, wid))
        r.response, r.responded_at = "needs_reconfirmation", None
        db.add(ShiftChangeEvent(tenant_id=tenant_id, site_id=o.site_id, worker_id=wid, shift_id=sh.shift_id, kind="changed", before=before, after=after, source_ref=f"offer:{o.id}", at=now))
        _tell(db, o, wid, "shift_changes", "offer.shift_changed", "Your shift has changed", "Please confirm the new details in the app.", f"offer:{o.id}:changed:{tag}", f"tempo://shifts/{sh.shift_id}",
              urgent=(aware(o.start_at) - now) <= SOON or (datetime.fromisoformat(before['start_at']) - now) <= SOON)
    else:
        if o.status == "pending_confirmation":
            r = db.get(ShiftOfferRecipient, (o.id, o.accepted_worker_id))
            r.response, r.responded_at = "pending", None
            wid, o.accepted_worker_id, o.status = o.accepted_worker_id, None, "open"
            _tell(db, o, wid, "offers", "offer.changed", "Shift offer changed", "The offer changed, so your acceptance was cleared. Please review it.", f"offer:{o.id}:changed:{tag}", f"tempo://offers/{o.id}")
        for r in db.scalars(select(ShiftOfferRecipient).where(ShiftOfferRecipient.offer_id == o.id, ShiftOfferRecipient.response == "pending")):
            _tell(db, o, r.worker_id, "offers", "offer.changed", "Shift offer changed", "The offer details changed.", f"offer:{o.id}:changed:{tag}:{r.worker_id}", f"tempo://offers/{o.id}")
    return o
