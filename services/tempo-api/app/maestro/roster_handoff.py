"""Outbound roster client for Overlay sites.

Same rule as app/maestro/writeback.py: no code path may report that a vendor accepted a roster unless a real connector
returned that. The default client therefore answers `unknown`, which Tempo records as `unconfirmed` and keeps open for
reconciliation. A real connector (Deputy, UKG, …) plugs in by implementing `VendorRosterClient`; none exists yet because
none can be built or verified without a sandbox connection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class HandoffOutcome:
    status: str  # confirmed | rejected | unknown
    detail: str = ""


class VendorRosterClient(Protocol):
    def submit_roster(self, site_id: str, payload_hash: str, shifts: list[dict[str, Any]], idempotency_key: str) -> HandoffOutcome: ...


class NotImplementedRosterClient:
    def submit_roster(self, site_id: str, payload_hash: str, shifts: list[dict[str, Any]], idempotency_key: str) -> HandoffOutcome:
        return HandoffOutcome("unknown", "no vendor roster connector is configured for this site — the outcome cannot be confirmed; use the file handoff or reconcile manually")


vendor_roster_client: VendorRosterClient = NotImplementedRosterClient()
