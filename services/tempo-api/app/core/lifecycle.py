"""Run lifecycle state machine — §10.

The "Allowed transition" column in §10 is transcribed directly into
TRANSITIONS below so the table in the spec and the enforced graph in code
can't drift silently — a reviewer can diff the two side by side.
"""
from __future__ import annotations

TERMINAL_STATES = {"completed", "completed_with_warnings", "failed", "cancelled", "expired"}

TRANSITIONS: dict[str, set[str]] = {
    "accepted": {"validating"},
    "validating": {"queued", "failed"},
    "queued": {"running", "cancelled"},
    "running": {"completed", "completed_with_warnings", "failed", "cancel_requested"},
    "cancel_requested": {"cancelled", "completed", "failed"},
    "completed": set(),
    "completed_with_warnings": set(),
    "failed": set(),
    "cancelled": set(),
    "expired": set(),
}


class InvalidTransition(ValueError):
    def __init__(self, from_state: str, to_state: str):
        super().__init__(f"cannot transition run from '{from_state}' to '{to_state}'")
        self.from_state = from_state
        self.to_state = to_state


def is_terminal(state: str) -> bool:
    return state in TERMINAL_STATES


def can_transition(from_state: str, to_state: str) -> bool:
    return to_state in TRANSITIONS.get(from_state, set())


def require_transition(from_state: str, to_state: str) -> None:
    if not can_transition(from_state, to_state):
        raise InvalidTransition(from_state, to_state)
