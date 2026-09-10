"""app/core/access_scope.py — §6.4's AccessScope resolver. Provider-
independent by construction: every test here builds a PrincipalContext
directly, the same way a real principal-resolution adapter would after
verifying a token, without needing any IdP to exist yet.
"""
from __future__ import annotations

import pytest

from app.core.access_scope import (
    AccessScope,
    PrincipalContext,
    authorises_customer,
    authorises_provider,
    authorises_site,
    authorises_worker_self,
    from_request_context,
    has_permission,
    resolve_access_scope,
)
from app.schemas.tenancy import RequestContext


def test_tenant_user_gets_permissions_for_their_roles():
    principal = PrincipalContext(
        principal_type="tenant_user",
        tenant_id="ten_1",
        roles=["operations_manager"],
        site_grants=["site_mel_01"],
    )
    scope = resolve_access_scope(principal)
    assert has_permission(scope, "labour.plan")
    assert has_permission(scope, "labour.approve")
    assert not has_permission(scope, "labour.configure")
    assert authorises_site(scope, "site_mel_01")
    assert not authorises_site(scope, "site_syd_01")


def test_empty_site_grants_authorise_nothing_never_everything():
    scope = resolve_access_scope(PrincipalContext(principal_type="tenant_user", tenant_id="ten_1", roles=["tenant_admin"]))
    assert scope.site_ids == frozenset()
    assert not authorises_site(scope, "site_mel_01")
    assert not authorises_site(scope, "any_site_at_all")


def test_labour_provider_user_gets_provider_scoped_permission():
    principal = PrincipalContext(
        principal_type="labour_provider_user",
        tenant_id="ten_1",
        roles=["labour_provider"],
        provider_grants=["prov_acme"],
    )
    scope = resolve_access_scope(principal)
    assert has_permission(scope, "labour.provider.manage")
    assert authorises_provider(scope, "prov_acme")
    assert not authorises_provider(scope, "prov_beta")


def test_role_granted_to_wrong_principal_type_is_dropped_not_trusted():
    # A tenant_user principal whose roles somehow include "labour_provider"
    # (a data error upstream, e.g. a misassigned UserRoleAssignment row)
    # must not pick up labour.provider.manage just because the string is
    # present -- the role's declared principal type has to match.
    principal = PrincipalContext(principal_type="tenant_user", tenant_id="ten_1", roles=["labour_provider", "operations_manager"])
    scope = resolve_access_scope(principal)
    assert not has_permission(scope, "labour.provider.manage")
    assert has_permission(scope, "labour.plan")  # operations_manager still applies, it's the right principal type


def test_worker_principal_has_no_labour_permissions_only_self_authority():
    scope = resolve_access_scope(PrincipalContext(principal_type="worker", tenant_id="ten_1", worker_self_id="wrk_5"))
    assert scope.permissions == frozenset()
    assert authorises_worker_self(scope, "wrk_5")
    assert not authorises_worker_self(scope, "wrk_6")


def test_kiosk_device_has_no_rbac_permissions():
    scope = resolve_access_scope(
        PrincipalContext(principal_type="kiosk_device", tenant_id="ten_1", site_grants=["site_mel_01"])
    )
    assert scope.permissions == frozenset()
    assert authorises_site(scope, "site_mel_01")


def test_integration_client_permissions_come_from_explicit_scopes_only():
    principal = PrincipalContext(
        principal_type="integration_client",
        tenant_id="ten_1",
        roles=["tenant_admin"],  # must be ignored -- integration clients aren't role-based
        explicit_scopes=frozenset({"labour.writeback"}),
    )
    scope = resolve_access_scope(principal)
    assert scope.permissions == frozenset({"labour.writeback"})
    assert not has_permission(scope, "labour.configure")


def test_support_operator_permissions_come_from_grant_scopes_only():
    principal = PrincipalContext(
        principal_type="support_operator",
        tenant_id="ten_1",
        explicit_scopes=frozenset({"labour.read"}),
        site_grants=["site_mel_01"],
    )
    scope = resolve_access_scope(principal)
    assert scope.permissions == frozenset({"labour.read"})
    assert authorises_site(scope, "site_mel_01")


def test_unknown_principal_type_is_rejected():
    with pytest.raises(ValueError):
        PrincipalContext(principal_type="not_a_real_type", tenant_id="ten_1")


def test_customer_grants_are_a_distinct_dimension_from_provider_grants():
    # §6.4: "Customer remains a security dimension for 3PL customer users.
    # Provider remains a separate security dimension for labour-hire
    # users. These dimensions must not be conflated." -- a principal with
    # only a customer grant must not authorise a provider check, and vice
    # versa.
    principal = PrincipalContext(
        principal_type="tenant_user",
        tenant_id="ten_1",
        roles=["executive"],
        customer_grants=["cust_A"],
    )
    scope = resolve_access_scope(principal)
    assert authorises_customer(scope, "cust_A")
    assert not authorises_provider(scope, "cust_A")
    assert scope.provider_ids == frozenset()


def test_from_request_context_bridges_the_legacy_header_shape():
    context = RequestContext(
        tenant_id="ten_1",
        site_ids=["site_mel_01"],
        customer_ids=["cust_A"],
        provider_id="prov_acme",
        user_id="usr_1",
        roles=["labour_provider"],
        purpose="labour.console",
        correlation_id="cor_1",
    )
    principal = from_request_context(context)
    assert principal.principal_type == "labour_provider_user"
    scope = resolve_access_scope(principal)
    assert has_permission(scope, "labour.provider.manage")
    assert authorises_provider(scope, "prov_acme")
    assert authorises_site(scope, "site_mel_01")
    assert authorises_customer(scope, "cust_A")


def test_access_scope_is_frozen_and_cannot_be_mutated_after_resolution():
    scope = resolve_access_scope(PrincipalContext(principal_type="tenant_user", tenant_id="ten_1", roles=["analyst"]))
    with pytest.raises(Exception):
        scope.permissions = frozenset({"labour.configure"})  # type: ignore[misc]
    assert isinstance(scope, AccessScope)
