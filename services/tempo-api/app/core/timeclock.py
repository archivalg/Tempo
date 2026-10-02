"""Internal time and attendance (roadmap M2): punch state machine, site policy, hours, supervisor daily list.

Rules this module enforces:
- Original punches are appended to `attendance_punch` and never edited or deleted. An approved correction (attendance_adjustment) is
  applied on top when hours are computed; the session row still shows what the worker actually did.
- A repeated tap of the same action inside the site's duplicate window returns the first result and records nothing new.
- At most one open native session per worker (partial unique index); a lost race is reported as a duplicate or a conflict, never two sessions.
- Worked, break and payable time are separate figures. Payable is worked minus unpaid breaks, then rounded as the site policy says.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import AttendanceStateConflict, GeofenceViolation
from app.models.attendance import AttendancePolicy, AttendancePunch, AttendanceRevision, SiteGeofence
from app.models.canonical import AttendanceSession, ShiftAssignment, Worker
from app.models.directory import WorkerPerson
from app.models.rosters import AttendanceAdjustment

SOURCE = "tempo_native"
EARLY_MATCH = timedelta(hours=4)  # a clock-in up to this long before a shift starts still belongs to that shift
ACTIONS = ("clock_in", "break_start", "break_end", "clock_out")
OPEN_STATES = ("working", "on_break")
POLICY_DEFAULTS = {"breaks_paid": False, "rounding_minutes": 0, "rounding_mode": "nearest", "duplicate_window_seconds": 30, "late_grace_minutes": 5,
                   "missing_punch_after_hours": 14.0, "excessive_hours": 12.0, "location_mode": "off"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(d: datetime | None) -> datetime | None:
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def site_of(db: Session, s: AttendanceSession) -> str:
    """The site a session belongs to: its own, or (older and imported rows) its worker's home site."""
    if s.site_id:
        return s.site_id
    w = db.get(Worker, s.worker_id)
    return w.home_site if w else ""


def get_policy(db: Session, tenant_id: str, site_id: str) -> AttendancePolicy:
    """The site's saved policy, or an unsaved object holding the documented defaults (the UI labels these as defaults)."""
    p = db.get(AttendancePolicy, (tenant_id, site_id))
    return p if p is not None else AttendancePolicy(tenant_id=tenant_id, site_id=site_id, **POLICY_DEFAULTS)


def policy_dict(p: AttendancePolicy, saved: bool) -> dict:
    return {"site_id": p.site_id, "breaks_paid": p.breaks_paid, "rounding_minutes": p.rounding_minutes, "rounding_mode": p.rounding_mode,
            "duplicate_window_seconds": p.duplicate_window_seconds, "late_grace_minutes": p.late_grace_minutes,
            "missing_punch_after_hours": p.missing_punch_after_hours, "excessive_hours": p.excessive_hours, "location_mode": p.location_mode, "is_default": not saved,
            "updated_by": p.updated_by or None, "updated_at": p.updated_at if saved else None}


# ------------------------------------------------------------------ location
@dataclass
class Fix:
    """What the kiosk's browser reported about its position. `error` is 'denied' or 'unavailable' when it could not."""
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    error: str | None = None


def assess_location(db: Session, tenant_id: str, site_id: str, mode: str, fix: Fix | None) -> dict:
    """Status, distance and the numbers to store. In 'require' mode anything but a position inside the fence is refused, before
    anything is recorded. In 'record' mode the punch always stands and the status is what a supervisor sees."""
    if mode == "off":
        return {"location_status": "not_requested"}
    fence = db.get(SiteGeofence, (tenant_id, site_id))
    if fix is None or fix.latitude is None or fix.longitude is None:
        status = "denied" if fix and fix.error == "denied" else "unavailable"
        if mode == "require":
            raise GeofenceViolation("This kiosk could not share its location, so the punch was not recorded. Allow location for this page, or ask a supervisor to record your time.")
        return {"location_status": status}
    from app.core.attendance import haversine_meters
    out = {"latitude": fix.latitude, "longitude": fix.longitude, "accuracy_m": fix.accuracy_m}
    if fence is None:
        if mode == "require":
            raise GeofenceViolation("This site has no geofence set, so location cannot be checked. Ask an administrator.")
        return {**out, "location_status": "no_fence"}
    d = haversine_meters(fix.latitude, fix.longitude, fence.latitude, fence.longitude)
    out["distance_m"] = round(d, 1)
    if d > fence.radius_meters:
        if mode == "require":
            raise GeofenceViolation(f"This kiosk is {d:.0f} m from the site (limit {fence.radius_meters:.0f} m), so the punch was not recorded. Tell a supervisor.")
        return {**out, "location_status": "outside"}
    return {**out, "location_status": "passed"}


# ------------------------------------------------------------------ punching
@dataclass
class PunchResult:
    session: AttendanceSession
    punch: AttendancePunch
    duplicate: bool
    matched_shift: ShiftAssignment | None = None


def open_session(db: Session, tenant_id: str, worker_id: str, *, lock: bool = False) -> AttendanceSession | None:
    q = select(AttendanceSession).where(AttendanceSession.tenant_id == tenant_id, AttendanceSession.worker_id == worker_id,
                                        AttendanceSession.state.in_(OPEN_STATES), AttendanceSession.source_system == SOURCE)
    return db.scalar(q.with_for_update() if lock else q)


def _last_punch(db: Session, session_id: str) -> AttendancePunch | None:
    return db.scalar(select(AttendancePunch).where(AttendancePunch.session_id == session_id).order_by(AttendancePunch.at.desc(), AttendancePunch.id.desc()).limit(1))


def match_shift(db: Session, tenant_id: str, worker_id: str, at: datetime) -> ShiftAssignment | None:
    rows = db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == tenant_id, ShiftAssignment.worker_id == worker_id, ShiftAssignment.status == "committed",
                                                    ShiftAssignment.end_at > at, ShiftAssignment.start_at <= at + EARLY_MATCH)).all()
    return min(rows, key=lambda h: abs((aware(h.start_at) - at).total_seconds()), default=None)


def _add_punch(db: Session, s: AttendanceSession, site_id: str, kind: str, at: datetime, device_id: str | None, source: str = "kiosk", note: str | None = None,
               loc: dict | None = None) -> AttendancePunch:
    p = AttendancePunch(tenant_id=s.tenant_id, site_id=site_id, session_id=s.id, worker_id=s.worker_id, kind=kind, at=at, device_id=device_id, source=source, note=note, **(loc or {}))
    db.add(p)
    db.flush()
    return p


def punch(db: Session, tenant_id: str, site_id: str, device_id: str | None, worker: Worker, action: str, now: datetime | None = None, fix: Fix | None = None) -> PunchResult:
    if action not in ACTIONS:
        raise AttendanceStateConflict(f"unknown action '{action}'")
    now = now or utcnow()
    pol = get_policy(db, tenant_id, site_id)
    window = timedelta(seconds=pol.duplicate_window_seconds)
    loc = assess_location(db, tenant_id, site_id, pol.location_mode, fix)
    s = open_session(db, tenant_id, worker.worker_id, lock=True)

    def repeat_of(sess: AttendanceSession | None) -> PunchResult | None:
        last = _last_punch(db, sess.id) if sess else None
        if last is not None and last.kind == action and now - aware(last.at) <= window:
            return PunchResult(sess, last, True)
        return None

    if action == "clock_in":
        if s is not None:
            dup = repeat_of(s)
            if dup:
                return dup
            raise AttendanceStateConflict(f"already clocked in (currently {'on a break' if s.state == 'on_break' else 'working'}) — clock out first")
        shift = match_shift(db, tenant_id, worker.worker_id, now)
        s = AttendanceSession(tenant_id=tenant_id, worker_id=worker.worker_id, start_at=now, end_at=None, approval="pending", source_system=SOURCE, site_id=site_id,
                              state="working", device_id=device_id, rostered_shift_id=shift.shift_id if shift else None)
        try:
            with db.begin_nested():
                db.add(s)
                db.flush()
        except IntegrityError:  # a concurrent clock-in won: treat ours as its repeat
            winner = open_session(db, tenant_id, worker.worker_id)
            dup = repeat_of(winner) if winner else None
            if dup:
                return dup
            raise AttendanceStateConflict("already clocked in") from None
        return PunchResult(s, _add_punch(db, s, site_id, "clock_in", now, device_id, loc=loc), False, shift)

    if s is None:
        # a repeat of a clock-out that already succeeded
        if action == "clock_out":
            prev = db.scalar(select(AttendanceSession).where(AttendanceSession.tenant_id == tenant_id, AttendanceSession.worker_id == worker.worker_id,
                                                             AttendanceSession.source_system == SOURCE, AttendanceSession.state == "closed").order_by(AttendanceSession.start_at.desc()).limit(1))
            last = _last_punch(db, prev.id) if prev else None
            if last is not None and last.kind == "clock_out" and now - aware(last.at) <= window:
                return PunchResult(prev, last, True)
        raise AttendanceStateConflict("not clocked in — clock in first")

    dup = repeat_of(s)
    if dup:
        return dup
    if action == "break_start":
        if s.state != "working":
            raise AttendanceStateConflict("already on a break")
        s.state, s.break_started_at = "on_break", now
        return PunchResult(s, _add_punch(db, s, site_id, "break_start", now, device_id, loc=loc), False)
    if action == "break_end":
        if s.state != "on_break":
            raise AttendanceStateConflict("not on a break")
        s.breaks_minutes = round((s.breaks_minutes or 0) + (now - aware(s.break_started_at)).total_seconds() / 60, 2)
        s.state, s.break_started_at = "working", None
        return PunchResult(s, _add_punch(db, s, site_id, "break_end", now, device_id, loc=loc), False)
    # clock_out (ends a running break first, recorded as an automatic break end)
    if s.state == "on_break":
        s.breaks_minutes = round((s.breaks_minutes or 0) + (now - aware(s.break_started_at)).total_seconds() / 60, 2)
        _add_punch(db, s, site_id, "break_end", now, device_id, source="auto", note="break ended by clock-out")
        s.break_started_at = None
    s.end_at, s.state = now, "closed"
    return PunchResult(s, _add_punch(db, s, site_id, "clock_out", now, device_id, loc=loc), False)


# ------------------------------------------------------------------ hours
def _round(minutes: float, step: int, mode: str) -> float:
    if step <= 0:
        return minutes
    q = minutes / step
    import math
    return step * (math.floor(q) if mode == "down" else math.ceil(q) if mode == "up" else math.floor(q + 0.5))


def effective(s: AttendanceSession, adj: AttendanceAdjustment | None, now: datetime) -> tuple[datetime, datetime | None, float]:
    """Start, end (None = still open) and break minutes after any APPROVED correction; the session row itself is untouched."""
    start, end, brk = aware(s.start_at), aware(s.end_at), s.breaks_minutes or 0.0
    if adj is not None and adj.state == "approved":
        start = aware(adj.requested_start) or start
        end = aware(adj.requested_end) or end
        brk = adj.requested_break_minutes if adj.requested_break_minutes is not None else brk
    return start, end, brk


def hours(s: AttendanceSession, adj: AttendanceAdjustment | None, policy: AttendancePolicy, now: datetime) -> dict:
    start, end, brk = effective(s, adj, now)
    to = end or now
    if s.state == "on_break" and s.break_started_at and end is None:
        brk += (now - aware(s.break_started_at)).total_seconds() / 60
    worked = max((to - start).total_seconds() / 60, 0.0)
    brk = min(brk, worked)
    deducted = 0.0 if policy.breaks_paid else brk
    payable = _round(max(worked - deducted, 0.0), policy.rounding_minutes, policy.rounding_mode)
    return {"start": start, "end": end, "worked_minutes": round(worked, 1), "break_minutes": round(brk, 1), "unpaid_break_minutes": round(deducted, 1),
            "payable_minutes": round(payable, 1), "rounded": policy.rounding_minutes > 0 and round(payable, 1) != round(max(worked - deducted, 0.0), 1)}


# ------------------------------------------------------------------ supervisor daily list
def _local_day(tz: ZoneInfo, day: str) -> tuple[datetime, datetime]:
    d = datetime.fromisoformat(day).date()
    a = datetime(d.year, d.month, d.day, tzinfo=tz)
    n = d + timedelta(days=1)
    return a.astimezone(timezone.utc), datetime(n.year, n.month, n.day, tzinfo=tz).astimezone(timezone.utc)


def daily_list(db: Session, tenant_id: str, site, day: str, now: datetime, *, can_see_names: bool) -> dict:
    """What a supervisor needs for one local day: rostered people who are late or absent, anyone still clocked in, sessions with a
    missing clock-out, attendance nobody rostered, and unusually long days. Computed on read from shifts, sessions and the site policy."""
    tz = ZoneInfo(site.timezone)
    d0, d1 = _local_day(tz, day)
    policy = get_policy(db, tenant_id, site.site_id)
    workers = {w.worker_id: w for w in db.scalars(select(Worker).where(Worker.tenant_id == tenant_id, Worker.home_site == site.site_id))}
    wids = list(workers) or [""]
    names = {p.worker_id: p.display_name for p in db.scalars(select(WorkerPerson).where(WorkerPerson.tenant_id == tenant_id, WorkerPerson.worker_id.in_(wids)))} if can_see_names else {}
    shifts = list(db.scalars(select(ShiftAssignment).where(ShiftAssignment.tenant_id == tenant_id, ShiftAssignment.worker_id.in_(wids), ShiftAssignment.status == "committed",
                                                           ShiftAssignment.start_at >= d0, ShiftAssignment.start_at < d1).order_by(ShiftAssignment.start_at)))
    sessions = list(db.scalars(select(AttendanceSession).where(AttendanceSession.tenant_id == tenant_id, AttendanceSession.worker_id.in_(wids),
                                                               ((AttendanceSession.start_at >= d0) & (AttendanceSession.start_at < d1)) | AttendanceSession.state.in_(OPEN_STATES)
                                                               ).order_by(AttendanceSession.start_at)))
    adjs = {a.session_id: a for a in db.scalars(select(AttendanceAdjustment).where(AttendanceAdjustment.tenant_id == tenant_id, AttendanceAdjustment.site_id == site.site_id,
                                                                                   AttendanceAdjustment.session_id.in_([x.id for x in sessions] or [""])).order_by(AttendanceAdjustment.requested_at))}
    pending = {a.session_id for a in adjs.values() if a.state == "pending"}
    label = lambda wid: names.get(wid) or f"Worker …{wid[-4:]}"  # noqa: E731
    by_shift = {x.rostered_shift_id: x for x in sessions if x.rostered_shift_id}
    claimed: set[str] = set()
    rows: list[dict] = []
    grace = timedelta(minutes=policy.late_grace_minutes)

    def sess_row(x: AttendanceSession, shift: ShiftAssignment | None, flags: list[str], **extra) -> dict:
        h = hours(x, adjs.get(x.id), policy, now)
        return {"worker_id": x.worker_id, "label": label(x.worker_id), "session_id": x.id, "state": x.state, "approval": x.approval, "clock_in": aware(x.start_at), "clock_out": aware(x.end_at),
                "scheduled_start": aware(shift.start_at) if shift else None, "scheduled_end": aware(shift.end_at) if shift else None, "role": shift.role if shift else None,
                "worked_hours": round(h["worked_minutes"] / 60, 2), "flags": flags, "pending_correction": x.id in pending, **extra}

    for sh in shifts:
        x = by_shift.get(sh.shift_id) or next((c for c in sessions if c.id not in claimed and c.worker_id == sh.worker_id and not c.rostered_shift_id
                                                and aware(sh.start_at) - EARLY_MATCH <= aware(c.start_at) < aware(sh.end_at)), None)
        if x is None:
            late_now = now > aware(sh.start_at) + grace
            rows.append({"worker_id": sh.worker_id, "label": label(sh.worker_id), "session_id": None, "state": "no_show" if late_now else "expected",
                         "approval": None, "clock_in": None, "clock_out": None, "scheduled_start": aware(sh.start_at), "scheduled_end": aware(sh.end_at), "role": sh.role, "worked_hours": 0.0,
                         "flags": ["no_show"] if late_now else [], "pending_correction": False, "minutes_late": None})
            continue
        claimed.add(x.id)
        flags: list[str] = []
        late = (aware(x.start_at) - aware(sh.start_at)) - grace
        minutes_late = round((aware(x.start_at) - aware(sh.start_at)).total_seconds() / 60) if late > timedelta(0) else 0
        if minutes_late:
            flags.append("late")
        rows.append(sess_row(x, sh, flags, minutes_late=minutes_late))
    for x in sessions:
        if x.id in claimed:
            continue
        rows.append(sess_row(x, None, ["unrostered"], minutes_late=None))
    for r in rows:
        if r["session_id"] is None:
            continue
        x = next(c for c in sessions if c.id == r["session_id"])
        if x.state in OPEN_STATES:
            age_h = (now - aware(x.start_at)).total_seconds() / 3600
            r["flags"].append("missing_clock_out" if age_h >= policy.missing_punch_after_hours else "open")
        if r["worked_hours"] >= policy.excessive_hours:
            r["flags"].append("excessive_hours")
        if r["pending_correction"]:
            r["flags"].append("correction_pending")
        if policy.location_mode != "off":
            st = [p.location_status for p in db.scalars(select(AttendancePunch).where(AttendancePunch.session_id == x.id))]
            if "outside" in st:
                r["flags"].append("outside_site")
            if any(v in ("unavailable", "denied") for v in st):
                r["flags"].append("no_location")
    counts: dict[str, int] = {}
    for r in rows:
        for f in r["flags"]:
            counts[f] = counts.get(f, 0) + 1
    return {"site": {"site_id": site.site_id, "name": site.name, "timezone": site.timezone}, "date": day, "as_of": now, "policy": policy_dict(policy, db.get(AttendancePolicy, (tenant_id, site.site_id)) is not None),
            "rows": rows, "counts": counts}


def revision(db: Session, s: AttendanceSession, action: str, actor: str, reason: str | None, h: dict) -> AttendanceRevision:
    r = AttendanceRevision(tenant_id=s.tenant_id, site_id=site_of(db, s), session_id=s.id, revision=s.revision, action=action, actor=actor, reason=reason,
                           snapshot={"worked_minutes": h["worked_minutes"], "break_minutes": h["break_minutes"], "payable_minutes": h["payable_minutes"],
                                     "start": h["start"].isoformat(), "end": h["end"].isoformat() if h["end"] else None})
    db.add(r)
    return r
