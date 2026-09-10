"""Tempo-owned identity, membership and session model — Production
Readiness spec §6.2's principal table and Appendix B's "Proposed Data
Changes", built provider-independently ahead of choosing a real OIDC
provider (ADR-0001, `docs/adr/0001-identity-provider.md`).

This is new, additive schema. Nothing in `app/dependencies.py` reads these
tables yet — `get_request_context` still trusts `X-Tempo-Context`
unchanged. Wiring a real OIDC-verified request to populate/consult these
tables is the remaining Phase 1 work this sprint deliberately did not do
without an approved identity-provider decision (see this session's own
instruction: "do not implement security-sensitive assumptions without
approval"). What exists here is the data model and
`app/core/access_scope.py`'s resolver logic against it, both fully
testable today with directly-constructed rows.

Consolidation note: Appendix B lists "Identity mapping" (external subject,
tenant, internal user, status, effective dates, entitlement source) as a
row distinct from "Tempo user" (external subject, account status, token
version, MFA policy reference, lifecycle timestamps) — the two overlap
enough (both keyed by external_subject) that duplicating them as separate
tables would just be two places to keep in sync. `TempoUser` here is the
global identity (one external_subject, platform-wide); `TenantMembership`
below is the per-tenant relationship "Identity mapping" was describing.
Flagged explicitly rather than silently picking one, since Appendix C's
Definition of Done expects requirements to be traceable to what was built.

Every grant table here is intentionally separate — `UserSiteGrant`,
`UserCustomerGrant`, `UserProviderGrant` — per §6.4's explicit instruction:
"Customer remains a security dimension for 3PL customer users. Provider
remains a separate security dimension for labour-hire users. These
dimensions must not be conflated." A join table covering all three would
have been less code; it would also have been the exact mistake §6.4 warns
against.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TempoUser(Base):
    """A human identity, platform-wide — not tenant-scoped itself (one
    person can hold memberships in more than one tenant, e.g. a
    labour-provider user supplying workers to several tenants). SEC-15's
    `token_version` is the revocation lever: bumping it invalidates every
    outstanding session for this user without touching session rows
    individually (role/password/MFA/status changes all bump it).
    """

    __tablename__ = "tempo_user"

    user_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    external_subject: Mapped[str] = mapped_column(String, unique=True, index=True)
    account_status: Mapped[str] = mapped_column(String, default="active")
    token_version: Mapped[int] = mapped_column(default=0)
    mfa_policy_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class TenantMembership(Base):
    """A user's relationship to one tenant — status, whether it's their
    default tenant on login, and the source of the invitation. Role
    assignment is a separate table (`UserRoleAssignment`) rather than a
    column here, since SEC-14 treats "roles" and "memberships" as
    separately auditable ("Persist users, tenant memberships, roles,
    permissions, user-site grants... as Tempo-owned authoritative data").
    """

    __tablename__ = "tenant_membership"

    user_id: Mapped[str] = mapped_column(String, ForeignKey("tempo_user.user_id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="active")
    is_default: Mapped[bool] = mapped_column(default=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invitation_source: Mapped[str | None] = mapped_column(String, nullable=True)


class UserRoleAssignment(Base):
    """One §5.2 role granted to a user within one tenant. Permission codes
    themselves stay centrally defined in code (`app/core/permissions.py`),
    never client- or database-supplied — this table only ever holds a role
    *name*, resolved to permissions at read time, the same
    role-name-to-permission-set indirection `RequestContext.has_permission`
    already uses today, just backed by real rows instead of a header.
    """

    __tablename__ = "user_role_assignment"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", "role", name="uq_user_role_assignment"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("tempo_user.user_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserSiteGrant(Base):
    __tablename__ = "user_site_grant"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", "site_id", name="uq_user_site_grant"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("tempo_user.user_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_id: Mapped[str] = mapped_column(String)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserCustomerGrant(Base):
    """Kept a distinct table from `UserProviderGrant` per §6.4 — see this
    module's docstring. Enforcement is gated on ADR-0007
    (`docs/adr/0007-customer-security-dimension.md`); the table and the
    resolver logic over it exist now regardless of that ADR's outcome.
    """

    __tablename__ = "user_customer_grant"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", "customer_id", name="uq_user_customer_grant"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("tempo_user.user_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    customer_id: Mapped[str] = mapped_column(String)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserProviderGrant(Base):
    """A labour-provider user's authority over one `LabourProvider`
    (`app/models/canonical.py`) — the user-facing counterpart to
    `RequestContext.provider_id`/`labour.provider.manage`, now backed by a
    real grant row instead of a caller-supplied context field.
    """

    __tablename__ = "user_provider_grant"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id", "provider_id", name="uq_user_provider_grant"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("tempo_user.user_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    provider_id: Mapped[str] = mapped_column(String, ForeignKey("labour_provider.provider_id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KioskDevice(Base):
    """An enrolled kiosk — §6.6: "A kiosk must first authenticate as an
    enrolled device bound to one tenant and a finite set of sites. Worker
    PIN or NFC presentation cannot establish or alter the kiosk's tenant
    scope." `credential_reference` is a Vault/hash reference, never a raw
    device secret (same convention as `MaestroConnection`'s credential
    handling in app/models/connectors.py).
    """

    __tablename__ = "kiosk_device"

    device_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_ids: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="active")
    credential_reference: Mapped[str | None] = mapped_column(String, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    config_version: Mapped[str] = mapped_column(String, default="1")


class ServiceClient(Base):
    """A Tempo-issued opaque credential for a direct integration client
    (SEC-22). Only `credential_prefix` (a short, safe-to-log lookup value)
    and `credential_hash` (never the secret itself) are stored — the same
    "store a hash, not the value" discipline as `WorkerCredential.pin_hash`
    (app/models/attendance.py), extended to service credentials.
    """

    __tablename__ = "service_client"

    client_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    credential_prefix: Mapped[str] = mapped_column(String, index=True)
    credential_hash: Mapped[str] = mapped_column(String)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    site_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class UserSession(Base):
    """A browser session (SEC-15) — rotating refresh credential, tracked as
    a family so a replayed/stale refresh token revokes the whole family,
    not just itself. Only digests are stored, never the refresh token or
    CSRF token values. Not usable until a real login flow populates it
    (Phase 1's remaining, IdP-dependent work) — the table exists now so
    `SecurityAuditEvent` rows and `AccessScope` resolution have somewhere
    real to point `session_id` at once that flow exists.
    """

    __tablename__ = "user_session"

    session_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    session_family_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("tempo_user.user_id"), index=True)
    refresh_token_digest: Mapped[str] = mapped_column(String)
    csrf_digest: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    replaced_by: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    device_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class PrivilegedSupportGrant(Base):
    """A time-bound, reasoned, approved support-operator grant (SEC-24,
    ADR-0008). `expires_at` is a column, not a constant, so ADR-0008's
    recommended ceiling (8 hours) is a data decision, not a code one — see
    that ADR's "built to be swappable" note.
    """

    __tablename__ = "privileged_support_grant"

    grant_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    operator_user_id: Mapped[str] = mapped_column(String, ForeignKey("tempo_user.user_id"), index=True)
    login_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    target_tenant_id: Mapped[str] = mapped_column(String, index=True)
    site_ids: Mapped[list] = mapped_column(JSON, default=list)
    action_categories: Mapped[list] = mapped_column(JSON, default=list)
    reason: Mapped[str] = mapped_column(String)
    approver_user_id: Mapped[str] = mapped_column(String, ForeignKey("tempo_user.user_id"))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SecurityAuditEvent(Base):
    """SEC-11/SEC-10: security-relevant decisions, never secrets. No
    column here may ever hold a token, PIN, credential, or raw payload —
    that constraint is enforced by review discipline (CODEOWNERS routes
    this file to @tempo-security-owners), the same way
    `app/maestro/writeback.py`'s "never fabricate confirmed" rule is
    enforced by review, not by a runtime check.
    """

    __tablename__ = "security_audit_event"

    event_id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    actor_type: Mapped[str] = mapped_column(String)
    actor_id: Mapped[str] = mapped_column(String, index=True)
    tenant_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    reason_code: Mapped[str | None] = mapped_column(String, nullable=True)
    session_or_grant_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
