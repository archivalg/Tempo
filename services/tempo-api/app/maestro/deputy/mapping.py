"""Deputy -> canonical mapping — Integration Spec §2.3.

Field names below (Id, Employee, StartTime, EndTime, ...) follow Deputy's
commonly-documented v1 REST resource shape but were NOT verified against a
live Deputy tenant (none was available while building this). Treat this
module as the right *shape* of a Deputy mapper — one function per §2.3
resource row, pure (no DB/network), returning a canonical envelope plus the
already-translated field dict — and adjust the literal field names against
Deputy's current API docs before pointing it at a real tenant. Everything
downstream (app/core/ingestion.py, the connector, the solvers) is
insulated from that detail by the canonical envelope contract.

Not implemented, and flagged rather than silently dropped: Skill/Certification
mapping (§2.3 notes Deputy has no native cert object — "map via custom
fields", which needs a per-tenant custom-field schema this scaffold doesn't
have), and TimesheetPayReturn (pay-rule/cost detail) — AttendanceSession's
pay_code is left unset. Both are listed in docs/roadmap.md as Phase B
follow-ups, not silently degraded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.envelope import CanonicalEnvelope, QualityInfo, SourceRef

MappingResult = tuple[CanonicalEnvelope, str, dict[str, Any]]  # (envelope, entity_type, canonical fields)


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _envelope(
    tenant_id: str,
    connection_id: str,
    event_type: str,
    site_id: str,
    record_id: str,
    modified_at: datetime,
    data: dict[str, Any],
    status: str,
    warnings: list[str],
) -> CanonicalEnvelope:
    now = datetime.now(timezone.utc)
    return CanonicalEnvelope(
        event_id=f"deputy:{connection_id}:{event_type}:{record_id}",
        event_type=event_type,
        occurred_at=modified_at,
        ingested_at=now,
        tenant_id=tenant_id,
        site_id=site_id,
        source=SourceRef(system="deputy", connection_id=connection_id, record_id=record_id, modified_at=modified_at),
        data=data,
        quality=QualityInfo(status=status, warnings=warnings),
    )


def map_employee(tenant_id: str, connection_id: str, site_id: str, record: dict[str, Any]) -> MappingResult:
    record_id = record.get("Id")
    warnings: list[str] = []
    if record_id is None:
        return (
            _envelope(tenant_id, connection_id, "worker.upserted", site_id, "unknown", datetime.now(timezone.utc), record, "rejected", ["missing required field 'Id'"]),
            "worker",
            {},
        )

    if "SubContractor" in record:
        employment_type = "labour_hire" if record["SubContractor"] else "permanent"
    else:
        employment_type = "permanent"
        warnings.append("no field to distinguish employment type; defaulted to 'permanent'")

    modified_at = _parse_dt(record.get("Modified")) or datetime.now(timezone.utc)
    fields = {
        "employment_type": employment_type,
        "home_site": site_id,
        "status": "active" if record.get("Active", True) else "inactive",
    }
    envelope = _envelope(
        tenant_id, connection_id, "worker.upserted", site_id, str(record_id), modified_at, record,
        "accepted_with_warnings" if warnings else "accepted", warnings,
    )
    return envelope, "worker", fields


def map_timesheet(tenant_id: str, connection_id: str, site_id: str, record: dict[str, Any]) -> MappingResult:
    record_id = record.get("Id")
    employee_id = record.get("Employee")
    start_time = record.get("StartTime")
    warnings: list[str] = []

    if record_id is None or employee_id is None or start_time is None:
        return (
            _envelope(tenant_id, connection_id, "attendance_session.upserted", site_id, str(record_id or "unknown"), datetime.now(timezone.utc), record, "rejected", ["missing Id, Employee, or StartTime"]),
            "attendance_session",
            {},
        )

    end_time = record.get("EndTime")
    if end_time is None:
        warnings.append("no EndTime — worker may still be clocked in")

    modified_at = _parse_dt(record.get("Modified")) or _parse_dt(start_time)
    fields = {
        "_source_worker_ref": str(employee_id),
        "start_at": _parse_dt(start_time),
        "end_at": _parse_dt(end_time),
        "breaks_minutes": float(record.get("Mealbreak", 0) or 0),
        "approval": "approved" if record.get("Approved") else "pending",
    }
    envelope = _envelope(
        tenant_id, connection_id, "attendance_session.upserted", site_id, str(record_id), modified_at, record,
        "accepted_with_warnings" if warnings else "accepted", warnings,
    )
    return envelope, "attendance_session", fields


def map_roster(
    tenant_id: str, connection_id: str, site_id: str, record: dict[str, Any], operational_unit_map: dict[str, tuple[str, str]] | None = None
) -> MappingResult:
    record_id = record.get("Id")
    employee_id = record.get("Employee")
    start_time = record.get("StartTime")
    end_time = record.get("EndTime")
    warnings: list[str] = []

    if record_id is None or employee_id is None or start_time is None or end_time is None:
        return (
            _envelope(tenant_id, connection_id, "shift_assignment.upserted", site_id, str(record_id or "unknown"), datetime.now(timezone.utc), record, "rejected", ["missing Id, Employee, StartTime or EndTime"]),
            "shift_assignment",
            {},
        )

    operational_unit_map = operational_unit_map or {}
    unit_id = str(record.get("OperationalUnit", ""))
    role, zone = operational_unit_map.get(unit_id, (None, None))
    if role is None:
        role, zone = "general", "general"
        warnings.append(f"OperationalUnit '{unit_id}' has no configured role/zone mapping; used 'general/general'")

    modified_at = _parse_dt(record.get("Modified")) or _parse_dt(start_time)
    fields = {
        "_source_worker_ref": str(employee_id),
        "role": role,
        "zone": zone,
        "start_at": _parse_dt(start_time),
        "end_at": _parse_dt(end_time),
        "status": "committed",
    }
    envelope = _envelope(
        tenant_id, connection_id, "shift_assignment.upserted", site_id, str(record_id), modified_at, record,
        "accepted_with_warnings" if warnings else "accepted", warnings,
    )
    return envelope, "shift_assignment", fields


def map_leave(tenant_id: str, connection_id: str, site_id: str, record: dict[str, Any]) -> MappingResult:
    record_id = record.get("Id")
    employee_id = record.get("Employee")
    start_date = record.get("StartDate")
    end_date = record.get("EndDate")
    warnings: list[str] = []

    if record_id is None or employee_id is None or start_date is None:
        return (
            _envelope(tenant_id, connection_id, "availability.upserted", site_id, str(record_id or "unknown"), datetime.now(timezone.utc), record, "rejected", ["missing Id, Employee or StartDate"]),
            "availability",
            {},
        )

    approved = record.get("Approved")
    if approved is None:
        warnings.append("no explicit approval flag; treated as pending leave (blocks availability conservatively)")
        status = "unavailable"
    else:
        status = "leave" if approved else "unavailable"

    modified_at = _parse_dt(record.get("Modified")) or _parse_dt(start_date)
    fields = {
        "_source_worker_ref": str(employee_id),
        "interval_start": _parse_dt(start_date),
        "interval_end": _parse_dt(end_date) or _parse_dt(start_date),
        "status": status,
        "preference": None,
    }
    envelope = _envelope(
        tenant_id, connection_id, "availability.upserted", site_id, str(record_id), modified_at, record,
        "accepted_with_warnings" if warnings else "accepted", warnings,
    )
    return envelope, "availability", fields
