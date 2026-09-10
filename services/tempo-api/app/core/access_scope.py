"""AccessScope — the one server-owned authorisation decision, §6.4:

"The canonical decision is Effective access equals Tenant membership
intersected with Role permissions, Site grants, Customer grants when
applicable, Provider grants when applicable, and Worker-self authority
when applicable... Create one AccessScope resolver used by every API,
export, comparison, monitoring query, action, worker and background job.
Local endpoint copies of entitlement logic are prohibited."

This resolver is deliberately provider-independent (ADR-0001,
`docs/adr/0001-identity-provider.md`): it consumes an already-resolved
`PrincipalContext` and never imports or references a specific identity
provider, token format, or verification library. Whatever eventually
verifies a caller's identity — a real OIDC-verified JWT, in production —
is a separate concern this module doesn't take on. That separation is what
lets this contract be built and fully unit-tested now, before ADR-0001 is
approved, instead of waiting for it.

**Not yet wired into any request handler.** `app/dependencies.py`'s
`get_request_context` is unchanged this sprint and still trusts
`X-Tempo-Context` unverified. `from_request_context` below exists only to
show how this resolver *would* consume the current header shape once a
real principal-resolution layer replaces it — it is not called from any
API route, and must not be treated as "the migration is done." Cutting
production traffic over to this resolver is exactly the "security-sensitive
assumption" this sprint was told not to implement without approval — that
cutover needs ADR-0001 approved and a real principal-resolution adapter
(reading TempoUser/TenantMembership/grants, or verifying a real token)
built first.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.core.permissions import ROLE_PRINCIPAL_TYPE, permissions_for_roles

# §6.2's seven rows.
PRINCIPAL_TYPES: frozenset[str] = frozenset(
    {
        "tenant_user",
        "worker",
        "labour_provider_user",
        "customer_user",
        "kiosk_device",
        "integration_client",
        "support_operator",
    }
)


@dataclass(frozen=True)
class PrincipalContext:
    """What's true about a caller before authorisation is resolved — this
    resolver's only input. For a real deployment this is populated from
    verified token claims plus a lookup against `app/models/identity.py`'s
    tables (TenantMembership, UserRoleAssignment, UserSiteGrant, ...), never
    from anything the caller supplies directly — `roles` here must already
    be the *server's* record of what roles this user holds, not a
    client-asserted list (SEC-02: "Ignore equivalent client headers").
    """

    principal_type: str
    tenant_id: str
    user_id: str | None = None  # None for kiosk_device / integration_client
    roles: list[str] = field(default_factory=list)
    site_grants: list[str] = field(default_factory=list)
    customer_grants: list[str] = field(default_factory=list)
    provider_grants: list[str] = field(default_factory=list)
    worker_self_id: str | None = None  # set only when principal_type == "worker"
    # integration_client's ServiceClient.scopes, support_operator's
    # PrivilegedSupportGrant.action_categories, or (once ADR-0007 lands) a
    # customer_user's explicit permission set — never a role-table lookup.
    explicit_scopes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.principal_type not in PRINCIPAL_TYPES:
            raise ValueError(f"unknown principal_type '{self.principal_type}'")


@dataclass(frozen=True)
class AccessScope:
    """The server-resolved result — the intended payload shape of
    `GET /v1/me/access` (Appendix A), once that endpoint exists. A
    requested tenant/site/customer/provider/worker identifier elsewhere in
    the API is only ever a *selector* checked against this — never
    authority by itself (§6.4's IDOR-tampering requirement, SEC-18).
    """

    tenant_id: str
    permissions: frozenset[str]
    site_ids: frozenset[str]
    customer_ids: frozenset[str]
    provider_ids: frozenset[str]
    worker_self_id: str | None


def resolve_access_scope(principal: PrincipalContext) -> AccessScope:
    """Effective access = tenant membership (implicit: a PrincipalContext
    only exists for one tenant_id) ∩ role permissions ∩ site/customer/
    provider grants ∩ worker-self authority, per principal type.
    """
    common = {
        "tenant_id": principal.tenant_id,
        "site_ids": frozenset(principal.site_grants),
    }

    if principal.principal_type in ("tenant_user", "labour_provider_user"):
        # A role belongs to exactly one principal type (app/core/permissions.py's
        # ROLE_PRINCIPAL_TYPE) — a role assigned to the wrong principal type
        # is a data error upstream (e.g. a labour_provider role row on a
        # tenant_user membership), and is dropped here rather than trusted,
        # the same "don't trust an inconsistent input" posture SEC-02 takes
        # toward client-supplied headers generally.
        allowed_roles = [r for r in principal.roles if ROLE_PRINCIPAL_TYPE.get(r) == principal.principal_type]
        return AccessScope(
            permissions=permissions_for_roles(allowed_roles),
            customer_ids=frozenset(principal.customer_grants),
            provider_ids=frozenset(principal.provider_grants),
            worker_self_id=None,
            **common,
        )

    if principal.principal_type == "worker":
        return AccessScope(
            permissions=frozenset(),  # worker authority is worker-self, not a labour.* permission
            customer_ids=frozenset(),
            provider_ids=frozenset(),
            worker_self_id=principal.worker_self_id,
            **common,
        )

    if principal.principal_type == "kiosk_device":
        return AccessScope(
            permissions=frozenset(),  # a kiosk is not an RBAC principal (§6.6)
            customer_ids=frozenset(),
            provider_ids=frozenset(),
            worker_self_id=None,
            **common,
        )

    # customer_user (pending ADR-0007), integration_client and
    # support_operator all resolve permissions from their own explicit
    # scopes, never a shared role table.
    return AccessScope(
        permissions=frozenset(principal.explicit_scopes),
        customer_ids=frozenset(principal.customer_grants),
        provider_ids=frozenset(principal.provider_grants),
        worker_self_id=None,
        **common,
    )


def has_permission(scope: AccessScope, permission: str) -> bool:
    return permission in scope.permissions


def authorises_site(scope: AccessScope, site_id: str) -> bool:
    """§6.4: 'All sites... must resolve to the current finite authorised
    set. An empty set means no access and must never mean no filter.' An
    empty `site_ids` therefore always returns False here, never True.
    """
    return site_id in scope.site_ids


def authorises_customer(scope: AccessScope, customer_id: str) -> bool:
    return customer_id in scope.customer_ids


def authorises_provider(scope: AccessScope, provider_id: str) -> bool:
    return provider_id in scope.provider_ids


def authorises_worker_self(scope: AccessScope, worker_id: str) -> bool:
    return scope.worker_self_id is not None and scope.worker_self_id == worker_id


def from_request_context(context, *, worker_self_id: str | None = None) -> PrincipalContext:
    """Demonstration/testing bridge only — builds a `PrincipalContext` from
    today's unverified `RequestContext` (app/schemas/tenancy.py), so this
    resolver's behaviour can be compared against the legacy header
    mechanism's current behaviour. **Never call this from a request
    handler**: `RequestContext` is exactly the client-asserted data SEC-02
    says must be ignored once a real principal-resolution layer exists.
    Its only legitimate caller today is a test (see
    tests/test_access_scope.py) or a future migration script reconciling
    the two mechanisms during cutover.
    """
    principal_type = "labour_provider_user" if "labour_provider" in context.roles else "tenant_user"
    return PrincipalContext(
        principal_type=principal_type,
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        roles=list(context.roles),
        site_grants=list(context.site_ids),
        customer_grants=list(context.customer_ids),
        provider_grants=[context.provider_id] if context.provider_id else [],
        worker_self_id=worker_self_id,
    )
