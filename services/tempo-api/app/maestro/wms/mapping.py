"""WMS backlog snapshot -> canonical mapping.

Field names below (`id`, `zone`, `intervalStart`, `backlogUnits`) are
illustrative, same caveat as client.py — no specific WMS vendor is named
in the spec, so there's no live wire format to verify against. Unlike the
Deputy/UKG mappings, there's no worker-reference to resolve here: a
backlog snapshot is a standalone zone/interval fact, not tied to a
specific worker, so it never needs the quarantine-until-dependency-arrives
handling those connectors use.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.schemas.envelope import CanonicalEnvelope, QualityInfo, SourceRef

MappingResult = tuple[CanonicalEnvelope, str, dict[str, Any]]


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def map_backlog_snapshot(tenant_id: str, connection_id: str, site_id: str, record: dict[str, Any]) -> MappingResult:
    record_id = record.get("id")
    zone = record.get("zone")
    interval_start = record.get("intervalStart")
    backlog_units = record.get("backlogUnits")
    warnings: list[str] = []

    if record_id is None or zone is None or interval_start is None or backlog_units is None:
        return (
            CanonicalEnvelope(
                event_id=f"wms:{connection_id}:zone_backlog.upserted:{record_id or 'unknown'}",
                event_type="zone_backlog.upserted",
                occurred_at=datetime.now(timezone.utc),
                ingested_at=datetime.now(timezone.utc),
                tenant_id=tenant_id,
                site_id=site_id,
                source=SourceRef(system="wms", connection_id=connection_id, record_id=str(record_id or "unknown"), modified_at=datetime.now(timezone.utc)),
                data=record,
                quality=QualityInfo(status="rejected", warnings=["missing id, zone, intervalStart or backlogUnits"]),
            ),
            "zone_backlog",
            {},
        )

    if backlog_units < 0:
        warnings.append(f"negative backlogUnits ({backlog_units}) treated as 0")

    modified_at = _parse_dt(record.get("modified")) or _parse_dt(interval_start)
    fields = {
        "site_id": site_id,
        "zone": zone,
        "interval_start": _parse_dt(interval_start),
        "backlog_units": max(0.0, float(backlog_units)),
    }
    envelope = CanonicalEnvelope(
        event_id=f"wms:{connection_id}:zone_backlog.upserted:{record_id}",
        event_type="zone_backlog.upserted",
        occurred_at=modified_at,
        ingested_at=datetime.now(timezone.utc),
        tenant_id=tenant_id,
        site_id=site_id,
        source=SourceRef(system="wms", connection_id=connection_id, record_id=str(record_id), modified_at=modified_at),
        data=record,
        quality=QualityInfo(status="accepted_with_warnings" if warnings else "accepted", warnings=warnings),
    )
    return envelope, "zone_backlog", fields
