"""Connector catalogue — Phase F's "connector catalogue" (§18).

A read registry describing what app/maestro/ actually implements, so a
tenant admin (or Prime) can discover available connectors over the API
instead of reading source code — nothing here is new integration logic,
it describes what Phase B/C already built. `source_system` values match
Appendix C's source_system enum exactly, and `POST /v1/connections`
(app/api/v1/onboarding.py) validates a new connection's source_system
against this catalogue.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectorDescriptor:
    source_system: str
    display_name: str
    entity_types: tuple[str, ...]
    auth_type: str
    status: str  # "ga" | "illustrative" — illustrative means no real vendor API to verify against
    notes: str


CONNECTOR_CATALOGUE: tuple[ConnectorDescriptor, ...] = (
    ConnectorDescriptor(
        source_system="deputy",
        display_name="Deputy",
        entity_types=("worker", "attendance_session", "shift_assignment", "availability"),
        auth_type="oauth2_bearer",
        status="ga",
        notes="Employee/Timesheet/Roster/Leave. Skill/certification mapping not covered (§2.3) — needs a per-tenant LMS/custom-field integration.",
    ),
    ConnectorDescriptor(
        source_system="ukg_pro_wfm",
        display_name="UKG Pro WFM",
        entity_types=("worker", "attendance_session", "shift_assignment", "availability"),
        auth_type="oauth2_tenant_key",
        status="ga",
        notes="Attendance/scheduling only; full UKG Pro HCM is explicitly out of scope per the spec.",
    ),
    ConnectorDescriptor(
        source_system="ukg_ready",
        display_name="UKG Ready",
        entity_types=("worker", "attendance_session", "shift_assignment", "availability"),
        auth_type="api_key",
        status="ga",
        notes="Same connector algorithm as UKG Pro WFM (app.maestro.ukg), a different client for a different auth/endpoint shape.",
    ),
    ConnectorDescriptor(
        source_system="wms",
        display_name="Warehouse Management System (illustrative)",
        entity_types=("zone_backlog",),
        auth_type="bearer_token",
        status="illustrative",
        notes="No vendor is named in the spec — adapt endpoint/field names to whichever WMS a real tenant runs.",
    ),
)

_BY_SOURCE_SYSTEM: dict[str, ConnectorDescriptor] = {c.source_system: c for c in CONNECTOR_CATALOGUE}


def get_connector(source_system: str) -> ConnectorDescriptor | None:
    return _BY_SOURCE_SYSTEM.get(source_system)
