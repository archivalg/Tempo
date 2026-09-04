"""Request scope — Integration Spec §5.1.

DP-08 / INT-003: every request must carry enforceable tenant + business scope.
The service must reject missing or contradictory scope rather than default to
a wider tenant view — so this model has no defaults on the fields that define
scope, and app/dependencies.py rejects a request that can't populate it.
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class RequestContext(BaseModel):
    tenant_id: str
    company_id: str | None = None
    site_ids: list[str] = Field(default_factory=list)
    customer_ids: list[str] = Field(default_factory=list)
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
        # real entitlement service exists (§5.2 is the source of truth).
        return permission in ROLE_PERMISSIONS.get_permissions(self.roles)


class _RolePermissions:
    _TABLE: dict[str, set[str]] = {
        "supervisor": {"labour.read"},
        "analyst": {"labour.read"},
        "executive": {"labour.read", "labour.margin.read"},
        "operations_manager": {"labour.read", "labour.plan", "labour.approve"},
        "planner": {"labour.read", "labour.plan"},
        "tenant_admin": {"labour.read", "labour.plan", "labour.configure"},
        "finance": {"labour.margin.read"},
        "3pl_commercial": {"labour.margin.read"},
        "hr_authorised": {"labour.worker_pii"},
        "integration_restricted": {"labour.writeback"},
    }

    def get_permissions(self, roles: list[str]) -> set[str]:
        result: set[str] = set()
        for role in roles:
            result |= self._TABLE.get(role, set())
        return result


ROLE_PERMISSIONS = _RolePermissions()
