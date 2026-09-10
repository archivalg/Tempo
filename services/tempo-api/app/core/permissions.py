"""The permission matrix — §5.2 (extended, see below) as a single,
centrally managed source of truth, per SEC-14 ("Persist users, tenant
memberships, roles, permissions... as Tempo-owned authoritative data")
and §6.4 ("Local endpoint copies of entitlement logic are prohibited").

Before this module, `app/schemas/tenancy.py` held the only copy of the
role->permission table, inline in `_RolePermissions._TABLE`. That module
now imports `ROLE_PERMISSION_MATRIX` from here rather than redefining it —
one table, not two independently-maintained copies that could silently
drift. This is a refactor, not a behaviour change: `RequestContext.has_permission`
resolves to exactly the same permissions as before.

§6.2's principal table has seven principal types; only one of them
("Tenant user") is meaningfully described by a role->permission lookup.
The other six have their own authority sources, listed here so this
module is a complete map of "who can do what" rather than a role table
that quietly ignores everything else:

- **Worker** — authority is "own worker record" (worker-self), not a
  `labour.*` permission at all. See `AccessScope.worker_self_id` in
  `app/core/access_scope.py`.
- **Labour-provider user** — a tenant_user-shaped principal whose role is
  `labour_provider`; permissions come from this matrix like any other
  role, but access is additionally intersected with `UserProviderGrant`
  (`app/models/identity.py`).
- **Customer user** — no role exists for this yet (ADR-0007,
  `docs/adr/0007-customer-security-dimension.md`, is not yet approved);
  once approved, the same pattern as labour-provider applies with
  `UserCustomerGrant`.
- **Kiosk device** — no `labour.*` permission; a kiosk authenticates as a
  device (`KioskDevice`), and worker PIN/NFC identifies who's using it,
  never what the kiosk itself may do beyond clock-in/out (§6.6).
- **Integration client** — permissions are the specific `scopes` recorded
  on its `ServiceClient` row (SEC-22), not a shared role table entry.
- **Support operator** — permissions are the specific `action_categories`
  on their live `PrivilegedSupportGrant` (SEC-24), never a standing role.

`PERMISSION_CODES` is the closed set of valid permission strings. Two of
the eight are not in the Integration Spec's original §5.2 table (which has
seven); `labour.provider.manage` was added when the Labour Provider role
was built, disclosed then as a pragmatic extension in
`app/schemas/tenancy.py`. Both are listed here as first-class, not as a
special case, now that this module exists as the one place to look.
"""
from __future__ import annotations

PERMISSION_CODES: frozenset[str] = frozenset(
    {
        "labour.read",
        "labour.plan",
        "labour.configure",
        "labour.approve",
        "labour.writeback",
        "labour.margin.read",
        "labour.worker_pii",
        "labour.provider.manage",
    }
)

# role name -> permission codes. Every role here is a "Tenant user"
# (§6.2) except labour_provider, which is a "Labour-provider user" —
# see ROLE_PRINCIPAL_TYPE below.
ROLE_PERMISSION_MATRIX: dict[str, frozenset[str]] = {
    "supervisor": frozenset({"labour.read"}),
    "analyst": frozenset({"labour.read"}),
    "executive": frozenset({"labour.read", "labour.margin.read"}),
    "operations_manager": frozenset({"labour.read", "labour.plan", "labour.approve"}),
    "planner": frozenset({"labour.read", "labour.plan"}),
    "tenant_admin": frozenset({"labour.read", "labour.plan", "labour.configure"}),
    "finance": frozenset({"labour.margin.read"}),
    "3pl_commercial": frozenset({"labour.margin.read"}),
    "hr_authorised": frozenset({"labour.worker_pii"}),
    "integration_restricted": frozenset({"labour.writeback"}),
    "labour_provider": frozenset({"labour.provider.manage"}),
}

# §6.2's principal type each role belongs to. Every role above is
# "tenant_user" except labour_provider — kept explicit rather than
# defaulted, so a future role addition has to state its principal type
# instead of silently inheriting "tenant_user".
ROLE_PRINCIPAL_TYPE: dict[str, str] = {
    "supervisor": "tenant_user",
    "analyst": "tenant_user",
    "executive": "tenant_user",
    "operations_manager": "tenant_user",
    "planner": "tenant_user",
    "tenant_admin": "tenant_user",
    "finance": "tenant_user",
    "3pl_commercial": "tenant_user",
    "hr_authorised": "tenant_user",
    "integration_restricted": "tenant_user",
    "labour_provider": "labour_provider_user",
}

assert set(ROLE_PERMISSION_MATRIX) == set(ROLE_PRINCIPAL_TYPE), "every role must have exactly one principal type"
assert all(perm in PERMISSION_CODES for perms in ROLE_PERMISSION_MATRIX.values() for perm in perms), (
    "every permission granted by a role must be one of the closed PERMISSION_CODES"
)


def permissions_for_roles(roles: list[str]) -> frozenset[str]:
    result: set[str] = set()
    for role in roles:
        result |= ROLE_PERMISSION_MATRIX.get(role, frozenset())
    return frozenset(result)
