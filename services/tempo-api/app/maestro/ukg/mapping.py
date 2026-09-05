"""Normalized-record -> canonical mapping shared by both UKG product lines
— Integration Spec §2.3. Each client (pro_wfm_client.py, ready_client.py)
absorbs its own vendor field names and yields the same normalized shape;
this module only knows that shape, not which product line produced it.

Not implemented, flagged rather than silently dropped: Skill/Certification
mapping — §2.3 states neither UKG product line natively covers this
("typically sourced from a separate LMS/compliance system"); Pay codes
(Pro WFM) for LabourCostRule — still tenant-configured directly, same gap
as Deputy's TimesheetPayReturn; and the full UKG Pro HCM product line,
which the spec itself deprioritizes ("materially heavier... only needed
for employee master sync, not attendance").
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.envelope import CanonicalEnvelope, QualityInfo, SourceRef

MappingResult = tuple[CanonicalEnvelope, str, dict[str, Any]]

# Approximate, illustrative keyword mapping — real UKG employment-category
# taxonomies vary by tenant configuration and should eventually be a
# per-tenant OptimisationPolicy mapping, not a hardcoded heuristic (same
# class of gap as the internal-min/hire-max ratio defaults in
# app/solvers/workforce_mix.py).
_CATEGORY_KEYWORDS = {
    "labour_hire": ("contract", "contingent", "temp", "agency"),
    "casual": ("casual",),
    "part_time": ("part",),
}


def _infer_employment_type(category: str | None) -> tuple[str, list[str]]:
    if not category:
        return "permanent", ["no employment-category field; defaulted to 'permanent'"]
    lowered = category.lower()
    for employment_type, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return employment_type, []
    return "permanent", []


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _envelope(
    tenant_id: str, connection_id: str, source_system: str, event_type: str, site_id: str,
    record_id: str, modified_at: datetime, data: dict[str, Any], status: str, warnings: list[str],
) -> CanonicalEnvelope:
    return CanonicalEnvelope(
        event_id=f"{source_system}:{connection_id}:{event_type}:{record_id}",
        event_type=event_type,
        occurred_at=modified_at,
        ingested_at=datetime.now(timezone.utc),
        tenant_id=tenant_id,
        site_id=site_id,
        source=SourceRef(system=source_system, connection_id=connection_id, record_id=record_id, modified_at=modified_at),
        data=data,
        quality=QualityInfo(status=status, warnings=warnings),
    )


def map_employee(tenant_id: str, connection_id: str, source_system: str, site_id: str, record: dict[str, Any]) -> MappingResult:
    record_id = record.get("id")
    if record_id is None:
        return (
            _envelope(tenant_id, connection_id, source_system, "worker.upserted", site_id, "unknown", datetime.now(timezone.utc), record, "rejected", ["missing employee id"]),
            "worker",
            {},
        )

    employment_type, warnings = _infer_employment_type(record.get("employment_category"))
    modified_at = _parse_dt(record.get("modified")) or datetime.now(timezone.utc)
    fields = {"employment_type": employment_type, "home_site": site_id, "status": "active" if record.get("active", True) else "inactive"}
    envelope = _envelope(
        tenant_id, connection_id, source_system, "worker.upserted", site_id, str(record_id), modified_at, record,
        "accepted_with_warnings" if warnings else "accepted", warnings,
    )
    return envelope, "worker", fields


def map_punch(tenant_id: str, connection_id: str, source_system: str, site_id: str, record: dict[str, Any]) -> MappingResult:
    record_id, employee_id, start = record.get("id"), record.get("employee_id"), record.get("start")
    if record_id is None or employee_id is None or start is None:
        return (
            _envelope(tenant_id, connection_id, source_system, "attendance_session.upserted", site_id, str(record_id or "unknown"), datetime.now(timezone.utc), record, "rejected", ["missing id, employee_id or start"]),
            "attendance_session",
            {},
        )

    warnings = []
    if record.get("end") is None:
        warnings.append("no end time — worker may still be clocked in")

    modified_at = _parse_dt(record.get("modified")) or _parse_dt(start)
    fields = {
        "_source_worker_ref": str(employee_id),
        "start_at": _parse_dt(start),
        "end_at": _parse_dt(record.get("end")),
        "breaks_minutes": 0.0,
        "approval": "approved" if record.get("approved") else "pending",
    }
    envelope = _envelope(
        tenant_id, connection_id, source_system, "attendance_session.upserted", site_id, str(record_id), modified_at, record,
        "accepted_with_warnings" if warnings else "accepted", warnings,
    )
    return envelope, "attendance_session", fields


def map_shift(
    tenant_id: str, connection_id: str, source_system: str, site_id: str, record: dict[str, Any],
    location_role_zone_map: dict[str, tuple[str, str]] | None = None,
) -> MappingResult:
    record_id, employee_id, start, end = record.get("id"), record.get("employee_id"), record.get("start"), record.get("end")
    if record_id is None or employee_id is None or start is None or end is None:
        return (
            _envelope(tenant_id, connection_id, source_system, "shift_assignment.upserted", site_id, str(record_id or "unknown"), datetime.now(timezone.utc), record, "rejected", ["missing id, employee_id, start or end"]),
            "shift_assignment",
            {},
        )

    location_role_zone_map = location_role_zone_map or {}
    location_code = str(record.get("location_code", ""))
    role, zone = location_role_zone_map.get(location_code, (None, None))
    warnings = []
    if role is None:
        role, zone = "general", "general"
        warnings.append(f"location code '{location_code}' has no configured role/zone mapping; used 'general/general'")

    modified_at = _parse_dt(record.get("modified")) or _parse_dt(start)
    fields = {"_source_worker_ref": str(employee_id), "role": role, "zone": zone, "start_at": _parse_dt(start), "end_at": _parse_dt(end), "status": "committed"}
    envelope = _envelope(
        tenant_id, connection_id, source_system, "shift_assignment.upserted", site_id, str(record_id), modified_at, record,
        "accepted_with_warnings" if warnings else "accepted", warnings,
    )
    return envelope, "shift_assignment", fields


def map_leave(tenant_id: str, connection_id: str, source_system: str, site_id: str, record: dict[str, Any]) -> MappingResult:
    record_id, employee_id, start = record.get("id"), record.get("employee_id"), record.get("start")
    if record_id is None or employee_id is None or start is None:
        return (
            _envelope(tenant_id, connection_id, source_system, "availability.upserted", site_id, str(record_id or "unknown"), datetime.now(timezone.utc), record, "rejected", ["missing id, employee_id or start"]),
            "availability",
            {},
        )

    approved = record.get("approved")
    status = "leave" if approved else "unavailable"
    warnings = [] if "approved" in record and record.get("approved") is not None else ["no explicit approval flag; treated as pending leave"]

    modified_at = _parse_dt(record.get("modified")) or _parse_dt(start)
    fields = {
        "_source_worker_ref": str(employee_id),
        "interval_start": _parse_dt(start),
        "interval_end": _parse_dt(record.get("end")) or _parse_dt(start),
        "status": status,
        "preference": None,
    }
    envelope = _envelope(
        tenant_id, connection_id, source_system, "availability.upserted", site_id, str(record_id), modified_at, record,
        "accepted_with_warnings" if warnings else "accepted", warnings,
    )
    return envelope, "availability", fields
