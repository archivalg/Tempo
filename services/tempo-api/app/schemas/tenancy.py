"""Request scope — Integration Spec §5.1.

DP-08 / INT-003: every request must carry enforceable tenant + business scope.
The service must reject missing or contradictory scope rather than default to
a wider tenant view — so this model has no defaults on the fields that define
scope, and app/dependencies.py rejects a request that can't populate it.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.core.permissions import permissions_for_roles


class RequestContext(BaseModel):
    tenant_id: str
    company_id: str | None = None
    site_ids: list[str] = Field(default_factory=list)
    customer_ids: list[str] = Field(default_factory=list)
    # Which LabourProvider (app/models/canonical.py) a labour_provider-role
    # caller manages. Distinct from company_id — that field is the Business
    # Spec §7 Company->Customer hierarchy for a 3PL serving its own
    # customers (stored but never enforced anywhere in this codebase);
    # this is a different hierarchy, a labour-hire agency supplying
    # workers *into* one tenant, with no equivalent in the Integration
    # Spec at all (§5.1's own RequestContext example has no such field).
    provider_id: str | None = None
    user_id: str
    roles: list[str] = Field(default_factory=list)
    purpose: str
    correlation_id: str

    @field_validator("tenant_id", "user_id", "purpose", "correlation_id")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("must not be empty")
        return value

    def has_permission(self, permission: str) -> bool:
        # Phase 0 stub: role -> permission mapping is a fixed table until the
        # real entitlement service exists. That table now lives in
        # app/core/permissions.py — §6.4's "one AccessScope resolver...
        # Local endpoint copies of entitlement logic are prohibited" applies
        # to this table too, so it is defined exactly once, there, not here.
        return permission in permissions_for_roles(self.roles)
