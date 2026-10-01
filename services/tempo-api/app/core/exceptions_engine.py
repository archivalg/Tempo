"""Live exception detection (Blueprint §7 lifecycle: detected → triaged → assigned → resolved/dismissed).

Pure derivation from roster + attendance + certification + source freshness. Every case keeps
the source occurrence time and Tempo's detection time, and repeats dedupe on `dedup_key` so
running detection every minute never multiplies cases. While a site's attendance source is
stale, absence-type findings (no_show, missing_punch) are *suppressed* — a dead feed must not
turn into a wall of false "no-shows" — and a `connector_stale` case is raised instead.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.canonical import AttendanceSession, ShiftAssignment, SkillCertification, Worker
from app.models.directory import DataSourceStatus, ExceptionCase

LATE_AFTER = timedelta(minutes=10)
NO_SHOW_AFTER = timedelta(minutes=20)
EARLY_MATCH = timedelta(minutes=45)     # a punch this far before shift start still matches it
OVERTIME_AFTER = timedelta(minutes=30)
MISSING_PUNCH_AFTER = timedelta(hours=2)  # still open this long after shift end
CERT_WINDOW = timedelta(days=14)
STATUS_OPEN = ("detected", "triaged", "assigned")


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def source_is_fresh(src: DataSourceStatus | None, now: datetime) -> bool:
    if src is None or src.mode in ("stale", "error", "not_configured") or src.last_success_at is None:
        return False
    return (now - _aware(src.last_success_at)).total_seconds() <= src.stale_after_seconds


def _upsert(db: Session, tenant_id: str, site_id: str, kind: str, severity: str, dedup: str, occurred: datetime,
            now: datetime, worker_id: str | None = None, shift_id: str | None = None, evidence: dict | None = None) -> bool:
    existing = db.scalar(select(ExceptionCase).where(ExceptionCase.tenant_id == tenant_id, ExceptionCase.dedup_key == dedup))
    if existing is not None:
        if existing.state in STATUS_OPEN:
            existing.severity = severity
            existing.evidence = {**(existing.evidence or {}), **(evidence or {})}
        return False
    db.add(ExceptionCase(tenant_id=tenant_id, site_id=site_id, kind=kind, severity=severity, dedup_key=dedup, worker_id=worker_id,
                         shift_id=shift_id, source_occurred_at=occurred, detected_at=now, evidence=evidence or {}))
    if severity in ("critical", "high"):  # one notice per case, to the people who can act on it at that site
        from app.core import notifications as nt
        nt.notify(db, tenant_id, nt.recipients(db, tenant_id, site_id, "labour.exception.manage"), kind=f"exception.{kind}", severity="urgent",
                  title=f"{kind.replace('_', ' ').capitalize()} — needs attention", body=f"{severity.capitalize()} severity at {site_id}.", link="/live", site_id=site_id, dedup_key=f"exception:{dedup}")
    return True


def detect_exceptions(db: Session, tenant_id: str, site_id: str, now: datetime | None = None) -> dict[str, int]:
    """Idempotent. Returns counts of newly detected cases by kind."""
    now = now or datetime.now(timezone.utc)
    new: dict[str, int] = {}

    def bump(kind: str, created: bool) -> None:
        if created:
            new[kind] = new.get(kind, 0) + 1

    att_src = db.get(DataSourceStatus, (tenant_id, site_id, "attendance"))
    att_fresh = source_is_fresh(att_src, now)
    if not att_fresh:
        bump("connector_stale", _upsert(
            db, tenant_id, site_id, "connector_stale", "high", f"stale:attendance:{site_id}", now, now,
            evidence={"source": "attendance", "detail": "Attendance source is not verified live; absence findings are suppressed."}))

    workers = {w.worker_id: w for w in db.scalars(select(Worker).where(Worker.tenant_id == tenant_id, Worker.home_site == site_id))}
    wids = list(workers)
    if not wids:
        return new
    win_start, win_end = now - timedelta(hours=18), now + timedelta(hours=1)
    shifts = db.scalars(select(ShiftAssignment).where(
        ShiftAssignment.tenant_id == tenant_id, ShiftAssignment.worker_id.in_(wids), ShiftAssignment.status == "committed",
        ShiftAssignment.end_at > win_start, ShiftAssignment.start_at < win_end)).all()
    sessions = db.scalars(select(AttendanceSession).where(
        AttendanceSession.tenant_id == tenant_id, AttendanceSession.worker_id.in_(wids),
        AttendanceSession.start_at > now - timedelta(hours=36))).all()

    by_worker_sessions: dict[str, list[AttendanceSession]] = {}
    for s in sessions:
        by_worker_sessions.setdefault(s.worker_id, []).append(s)
    matched_session_ids: set[str] = set()

    for sh in shifts:
        start, end = _aware(sh.start_at), _aware(sh.end_at)
        cands = [s for s in by_worker_sessions.get(sh.worker_id, [])
                 if _aware(s.start_at) >= start - EARLY_MATCH and _aware(s.start_at) < end]
        sess = min(cands, key=lambda s: _aware(s.start_at)) if cands else None
        if sess is not None:
            matched_session_ids.add(sess.id)
            delay = _aware(sess.start_at) - start
            if delay > LATE_AFTER:
                mins = int(delay.total_seconds() // 60)
                bump("late", _upsert(db, tenant_id, site_id, "late", "medium" if mins < 30 else "high", f"late:{sh.shift_id}",
                                     _aware(sess.start_at), now, sh.worker_id, sh.shift_id, {"minutes_late": mins}))
            if sess.end_at is None and now > end + OVERTIME_AFTER and now <= end + MISSING_PUNCH_AFTER:
                bump("overtime", _upsert(db, tenant_id, site_id, "overtime", "medium", f"ot:{sh.shift_id}", end, now, sh.worker_id, sh.shift_id,
                                         {"minutes_over": int((now - end).total_seconds() // 60)}))
            if sess.end_at is None and now > end + MISSING_PUNCH_AFTER and att_fresh:
                bump("missing_punch", _upsert(db, tenant_id, site_id, "missing_punch", "high", f"mp:{sh.shift_id}", end, now, sh.worker_id, sh.shift_id,
                                              {"detail": "No clock-out recorded after shift end"}))
            if sess.end_at is not None and _aware(sess.end_at) < end - timedelta(minutes=30):
                bump("early_departure", _upsert(db, tenant_id, site_id, "early_departure", "low", f"ed:{sh.shift_id}", _aware(sess.end_at), now,
                                                sh.worker_id, sh.shift_id, {"minutes_early": int((end - _aware(sess.end_at)).total_seconds() // 60)}))
        elif att_fresh and now > start + NO_SHOW_AFTER and now < end:
            mins = int((now - start).total_seconds() // 60)
            bump("no_show", _upsert(db, tenant_id, site_id, "no_show", "critical" if mins > 60 else "high", f"ns:{sh.shift_id}", start, now,
                                    sh.worker_id, sh.shift_id, {"minutes_since_start": mins}))

    if att_fresh:
        for s in sessions:
            if s.id in matched_session_ids:
                continue
            start = _aware(s.start_at)
            covered = any(sh.worker_id == s.worker_id and _aware(sh.start_at) - EARLY_MATCH <= start < _aware(sh.end_at) for sh in shifts)
            if not covered and start > now - timedelta(hours=12):
                bump("unrostered", _upsert(db, tenant_id, site_id, "unrostered", "high", f"un:{s.id}", start, now, s.worker_id, None,
                                           {"detail": "Clock-in with no matching rostered shift", "attendance_session_id": s.id}))

    rostered_soon = {sh.worker_id for sh in db.scalars(select(ShiftAssignment).where(
        ShiftAssignment.tenant_id == tenant_id, ShiftAssignment.worker_id.in_(wids), ShiftAssignment.status == "committed",
        ShiftAssignment.start_at >= now, ShiftAssignment.start_at < now + timedelta(days=7)))}
    for cert in db.scalars(select(SkillCertification).where(SkillCertification.tenant_id == tenant_id, SkillCertification.worker_id.in_(list(rostered_soon) or [""]),
                                                            SkillCertification.valid_to.is_not(None))):
        vt = _aware(cert.valid_to)
        if vt < now + CERT_WINDOW:
            expired = vt < now
            bump("cert_expiry", _upsert(db, tenant_id, site_id, "cert_expiry", "high" if expired else "medium", f"cert:{cert.id}", (vt if expired else now), now, cert.worker_id, None,
                                        {"skill": cert.skill_code, "valid_to": vt.isoformat(), "expired": expired}))
    return new
