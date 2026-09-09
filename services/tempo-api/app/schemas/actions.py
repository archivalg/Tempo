"""Controlled action contracts — Integration Spec §12, Appendix C."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

ActionType = Literal["publish_roster", "update_assignment", "approve_leave", "create_training_plan"]
ActionStatus = Literal[
    "validated", "approved", "submitted", "confirmed", "partially_confirmed", "rejected", "unknown", "compensated"
]

# Which run_type's recommendation each action_type is allowed to act on —
# not named explicitly in the spec text, but implied by each action's
# description (§12.1) and the models each run_type actually produces.
ACTION_TYPE_RUN_TYPE: dict[str, str] = {
    "publish_roster": "named_roster",
    "update_assignment": "intraday_reallocation",
    "approve_leave": "leave_rdo",
    "create_training_plan": "training_coverage",
}

# The source-side resource an action_type mutates — keys
# SourceVersionWatermark rows so unrelated action types on the same
# site/connection don't collide on one version counter.
RESOURCE_TYPE_BY_ACTION: dict[str, str] = {
    "publish_roster": "roster",
    "update_assignment": "assignment",
    "approve_leave": "leave",
    "create_training_plan": "training_plan",
}


class ActionTarget(BaseModel):
    system: str
    connection_id: str
    site_id: str


class ActionValidateRequest(BaseModel):
    """§12.2's two-step action contract, step 1."""

    action_type: ActionType
    recommendation_id: str
    target: ActionTarget
    expected_source_version: str | None = None


class ActionValidateResponse(BaseModel):
    action_id: str
    action_token: str
    status: ActionStatus
    impact_summary: dict[str, Any]
    expires_at: datetime


class ActionExecuteRequest(ActionValidateRequest):
    """§12.2 step 2 — repeats step 1's fields so the server can recompute
    and compare the payload hash, not just trust the stored copy from
    validation; only action_id/action_token are new.
    """

    action_id: str
    action_token: str


class ActionResponse(BaseModel):
    action_id: str
    status: ActionStatus
    detail: str | None = None
