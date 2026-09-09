"""Native writeback — the one "vendor" Tempo genuinely controls: itself.

Standalone mode means Tempo IS the T&A system, so publishing a roster or
approving leave for a `target.system == "tempo_native"` action doesn't
need an external vendor call at all — it's a direct, real write to
Tempo's own canonical tables. Unlike `app.maestro.writeback`'s
`NotImplementedWritebackClient` (a stand-in for the Overlay case: a real
Deputy/UKG/etc write API this codebase has no credential for), this
client's `submit` genuinely commits the change and its `confirmed` is
real, not a shortcut. Selected in app/api/v1/actions.py based on the
action's target system — see `_get_writeback_client` there.

Scope: `publish_roster` and `approve_leave` only. `update_assignment`
(intraday_reallocation) and `create_training_plan` don't have a defined
native write target — what "committing" an intraday move or a training
plan means for Tempo's own canonical tables isn't specified anywhere in
the source docs — so both still report `unknown` even for a tempo_native
target, disclosed rather than guessed at.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.maestro.writeback import WritebackOutcome
from app.models.canonical import Availability, ShiftAssignment
from app.models.runs import Recommendation
from app.solvers.shifts import SHIFT_CALENDAR

_SHIFT_BY_CODE = {shift.code: shift for shift in SHIFT_CALENDAR}
_UNIMPLEMENTED_DETAIL = "native writeback for action_type '{action_type}' has no defined write target — not implemented"


class TempoNativeWritebackClient:
    def __init__(self, db: Session, tenant_id: str):
        self._db = db
        self._tenant_id = tenant_id

    def submit(self, action_type: str, target: dict[str, Any], payload: dict[str, Any]) -> WritebackOutcome:
        if action_type == "publish_roster":
            return self._publish_roster(payload["recommendation_id"])
        if action_type == "approve_leave":
            return self._approve_leave(payload["recommendation_id"])
        return WritebackOutcome(status="unknown", detail=_UNIMPLEMENTED_DETAIL.format(action_type=action_type))

    def check_status(self, action_type: str, target: dict[str, Any], payload: dict[str, Any]) -> WritebackOutcome:
        # Native writes commit synchronously inside submit() — there is
        # nothing pending to reconcile, unlike a real vendor call whose
        # outcome might genuinely be unknown after submission.
        return WritebackOutcome(status="confirmed", detail="native writes commit synchronously; nothing to reconcile")

    def _recommendation(self, recommendation_id: str) -> Recommendation | None:
        return self._db.get(Recommendation, recommendation_id)

    def _publish_roster(self, recommendation_id: str) -> WritebackOutcome:
        """`solve_named_roster` already writes a `ShiftAssignment` row per
        assignment at status="proposed" (that's how the run's own result
        gets a canonical record at all, independent of whether it's ever
        published — see app/solvers/named_roster.py). Publishing means
        promoting those existing rows to "committed", never inserting a
        second row — this was a real bug caught while building this:
        the first version blindly inserted a fresh row per assignment,
        silently doubling every published run's ShiftAssignment rows
        (14 solved + 14 inserted = 28, one seeded scenario's exact
        reproduction).
        """
        recommendation = self._recommendation(recommendation_id)
        if recommendation is None:
            return WritebackOutcome(status="rejected", detail=f"recommendation '{recommendation_id}' not found")
        assignments = (recommendation.body.get("result") or {}).get("assignments", [])
        if not assignments:
            return WritebackOutcome(status="rejected", detail="recommendation has no assignments to publish")

        committed = 0
        not_found = 0
        for row in assignments:
            shift = _SHIFT_BY_CODE.get(row["shift_code"])
            if shift is None:
                not_found += 1
                continue
            day = datetime.fromisoformat(row["day"]).replace(tzinfo=timezone.utc)
            proposed = self._db.scalar(
                select(ShiftAssignment)
                .where(ShiftAssignment.tenant_id == self._tenant_id)
                .where(ShiftAssignment.worker_id == row["worker_id"])
                .where(ShiftAssignment.role == row["role"])
                .where(ShiftAssignment.zone == row["zone"])
                .where(ShiftAssignment.start_at == day + timedelta(hours=shift.start_hour))
                .where(ShiftAssignment.end_at == day + timedelta(hours=shift.end_hour))
                .where(ShiftAssignment.status == "proposed")
            )
            if proposed is None:
                not_found += 1
                continue
            proposed.status = "committed"
            committed += 1
        self._db.flush()
        detail = f"committed {committed} of {len(assignments)} proposed shift assignment(s)"
        if not_found:
            detail += f"; {not_found} had no matching proposed row (already committed, or superseded by a later run)"
        if committed == 0:
            status = "rejected"
        elif committed < len(assignments):
            status = "partially_confirmed"
        else:
            status = "confirmed"
        return WritebackOutcome(status=status, detail=detail)

    def _approve_leave(self, recommendation_id: str) -> WritebackOutcome:
        recommendation = self._recommendation(recommendation_id)
        if recommendation is None:
            return WritebackOutcome(status="rejected", detail=f"recommendation '{recommendation_id}' not found")
        decisions = (recommendation.body.get("result") or {}).get("decisions", [])
        if not decisions:
            return WritebackOutcome(status="rejected", detail="recommendation has no decisions to apply")

        approved_decisions = [d for d in decisions if d.get("approved")]
        if not approved_decisions:
            # A legitimate outcome (severe staffing shortage can mean the
            # recommendation approves nobody) — nothing to write is not a
            # failure, so this must not report "rejected".
            return WritebackOutcome(status="confirmed", detail="no leave/RDO requests were approved by this recommendation — nothing to apply")

        applied = 0
        for decision in approved_decisions:
            rows = self._db.scalars(
                select(Availability)
                .where(Availability.tenant_id == self._tenant_id)
                .where(Availability.worker_id == decision["worker_id"])
                .where(Availability.status.in_(["leave_requested", "rdo_requested"]))
            ).all()
            for row in rows:
                if row.interval_start.date().isoformat() != decision["day"]:
                    continue
                row.status = "leave" if decision["request_type"] == "leave" else "rdo"
                applied += 1
        self._db.flush()
        detail = f"applied {applied} of {len(approved_decisions)} approved leave/RDO decision(s)"
        if applied == 0:
            status = "rejected"
        elif applied < len(approved_decisions):
            status = "partially_confirmed"
        else:
            status = "confirmed"
        return WritebackOutcome(status=status, detail=detail)
