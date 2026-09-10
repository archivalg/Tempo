# ADR-0008: Privileged support grant and step-up policy

**Status**: Proposed — awaiting approval
**Decision owner**: CEO, operations, security (Appendix D: "before Phase 1 exit")

## Context

SEC-24 requires "privileged support access only through step-up
authentication and a reasoned, approved, time-bound, tenant-targeted grant
with immutable audit events." SEC-12 requires break-glass administration
to be documented "with approval, expiry and retrospective review." No such
mechanism exists today — any caller who can construct an
`X-Tempo-Context` header with `tenant_admin` in `roles` has full tenant
authority, permanently, with no time bound or approval trail.

## Options considered

1. **Formal, narrow, time-bound support-grant workflow** — a support
   operator authenticates as themselves (not as a tenant user), requests a
   grant naming a target tenant, a finite site set, and specific action
   categories, with a mandatory reason; an approver signs off; the grant
   expires automatically; every action taken under it is tagged with the
   grant's identifier in `SecurityAuditEvent`.
2. **Ad hoc tenant-admin impersonation** (effectively today's status quo,
   formalized) — rejected: fails SEC-24 outright (no approval, no expiry,
   no distinct audit trail distinguishing a support operator from a real
   tenant admin).
3. **No support access at all; require the customer to grant temporary
   tenant-admin access themselves** — simpler to build, but contradicts
   the spec's own explicit inclusion of a "Support operator" principal
   type (§6.2) and would make routine diagnosis dependent on customer
   availability, unworkable for a supportable enterprise service (the
   spec's own stated end goal, §1).

## Recommendation

**Option 1**, with these specific parameters (recommended defaults, not yet
approved): grants expire after a **maximum of 8 hours**, require **step-up
re-authentication** (not just an already-open session) to request, require
a **free-text reason** at request time, and produce an immutable
`SecurityAuditEvent` row for the grant's creation, every action taken under
it, and its expiry/termination.

## Trade-offs

- An 8-hour ceiling may be too short for a genuinely long diagnostic
  session — mitigated by allowing a new grant request (with a fresh
  approval) rather than an extension, which keeps the audit trail as a
  sequence of discrete, separately-approved windows rather than one
  open-ended one.
- Step-up re-authentication adds friction to support workflows — accepted
  deliberately; SEC-24's own text requires it, and the alternative (a
  standing support session with tenant-admin-equivalent authority) is
  exactly the risk this control exists to close.
- This ADR proposes specific numbers (8 hours) the spec itself doesn't
  fix — flagged explicitly as *this sprint's recommendation*, not a
  requirement already approved; the decision owner may set a different
  ceiling.

## Cost

Primarily engineering effort to build the grant-request/approval workflow,
the `PrivilegedSupportGrant` table (built this sprint, see
`app/models/identity.py`), and the AccessScope resolver's support-operator
branch (also built this sprint, gated on this ADR before it's wired to any
real endpoint). No material infrastructure cost.

## Exact work this decision blocks

The actual support-grant *request/approval UI or API* (not built this
sprint — the data model and resolver logic are, but issuing a live grant to
a real support operator against a real tenant needs this ADR approved
first, per the "do not implement security-sensitive assumptions without
approval" instruction this sprint operated under). SEC-12's break-glass
procedure documentation also depends on this ADR's approved parameters.

## Built to be swappable

`app/models/identity.py`'s `PrivilegedSupportGrant` table and
`app/core/access_scope.py`'s support-operator resolution branch are built
against the *shape* of this decision (time-bound, reasoned, approved,
tenant-targeted) without hardcoding the 8-hour figure — `expires_at` is a
column, not a constant, so a different ceiling is a data change, not a
code change.
