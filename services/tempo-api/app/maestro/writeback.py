"""Writeback submission — Integration Spec §12.

No real vendor writeback API is implemented here, for the same reason
WMS's read-side client is illustrative and Deputy/UKG never got a *write*
client: §18.1 itself says "Writeback should not be part of MVP unless a
named pilot requires it and the source offers a reversible staging
state," and there's no live tenant or sandbox credential to build or
verify a real one against.

Rather than fabricate a "confirmed" outcome no live vendor ever actually
returned, the default client is honest about not knowing: every
submission comes back `unknown`, forcing exactly the reconciliation path
a real, still-processing vendor call would need — never a convenient
(and false) `confirmed`. This is a stronger claim than WMS's "adapt the
endpoint names" gap: there is currently no code path in this service that
can honestly report a source system accepted a write, by design, until a
real Maestro writeback connector is built.

app/api/v1/actions.py depends on the `WritebackClient` protocol, not this
module's default directly, so a real connector can be substituted later
without changing the action pipeline — and tests substitute a
`FakeWritebackClient` (see tests/test_actions.py) the same way connector
tests substitute fake HTTP clients for Deputy/UKG/WMS reads.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class WritebackOutcome:
    status: str  # confirmed | partially_confirmed | rejected | unknown
    detail: str = ""


class WritebackClient(Protocol):
    def submit(self, action_type: str, target: dict[str, Any], payload: dict[str, Any]) -> WritebackOutcome: ...

    def check_status(self, action_type: str, target: dict[str, Any], payload: dict[str, Any]) -> WritebackOutcome: ...


class NotImplementedWritebackClient:
    """The honest default — see module docstring."""

    def submit(self, action_type: str, target: dict[str, Any], payload: dict[str, Any]) -> WritebackOutcome:
        return WritebackOutcome(
            status="unknown",
            detail="no real vendor writeback connector is implemented — outcome cannot be confirmed without reconciliation",
        )

    def check_status(self, action_type: str, target: dict[str, Any], payload: dict[str, Any]) -> WritebackOutcome:
        return WritebackOutcome(
            status="unknown",
            detail="no real vendor writeback connector is implemented — status cannot be queried",
        )


default_writeback_client: WritebackClient = NotImplementedWritebackClient()
