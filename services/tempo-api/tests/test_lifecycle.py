import pytest

from app.core.lifecycle import InvalidTransition, can_transition, is_terminal, require_transition


def test_happy_path_transitions_allowed():
    for pair in [
        ("accepted", "validating"),
        ("validating", "queued"),
        ("queued", "running"),
        ("running", "completed"),
    ]:
        assert can_transition(*pair)


def test_terminal_states_have_no_outgoing_transitions():
    for state in ["completed", "completed_with_warnings", "failed", "cancelled", "expired"]:
        assert is_terminal(state)
        assert can_transition(state, "validating") is False


def test_require_transition_raises_on_illegal_edge():
    with pytest.raises(InvalidTransition):
        require_transition("completed", "running")


def test_cancel_requested_only_reachable_from_running():
    assert can_transition("running", "cancel_requested")
    assert not can_transition("queued", "cancel_requested")
    assert not can_transition("accepted", "cancel_requested")
