# Mobilisation Sprint Review

Covers the five-day mobilisation sprint: Phase 0 code/config work plus
draft ADRs, and provider-independent Phase 1 foundations (principal types,
the AccessScope contract, permission matrix, tenant-isolation inventory,
negative tests). Source baseline: this repo's `main` branch as of the
Labour Provider role commit; this sprint's own commit follows this
document.

## What's built (working evidence)

**Phase 0:**
- `.github/CODEOWNERS` — routes API, security-sensitive files, integration
  runtime, console, infra, and docs to placeholder teams (real handles
  still needed — see Outstanding approvals).
- 10 ADRs (`docs/adr/`) covering every Appendix D technical decision:
  identity provider, Oracle topology, queue technology, deployment
  runtime, first pilot connectors, first writeback action, customer as a
  security dimension, privileged support grant policy, direct-connector-
  vs-Maestro, Oracle VPD scope. Each has a recommendation, trade-offs,
  cost, and the exact work it blocks.
- `docs/pilot-charter.md`, `docs/environment-access-matrix.md` — templated
  against the existing demo tenant, explicitly marked draft/TBD wherever a
  commercial decision (pilot customer, site, success measures) is still
  needed.
- `docs/roadmap.md` — P0-08's solver freeze recorded, scoped precisely
  (blocks new solver families only, not this sprint's own work or Phase
  6's calibration of existing models).

**Phase 1 foundations (provider-independent):**
- `app/models/identity.py` — 9 new tables: `TempoUser`, `TenantMembership`,
  `UserRoleAssignment`, `UserSiteGrant`/`UserCustomerGrant`/`UserProviderGrant`
  (kept separate per §6.4's explicit instruction), `KioskDevice`,
  `ServiceClient`, `UserSession`, `PrivilegedSupportGrant`,
  `SecurityAuditEvent`. Verified to create cleanly alongside every
  existing table (37 total).
- `app/core/permissions.py` — the permission matrix, now the single
  source of truth (`app/schemas/tenancy.py` imports from it instead of
  keeping its own copy — a refactor, not a behaviour change, confirmed by
  the full suite staying green).
- `app/core/access_scope.py` — the `AccessScope` resolver: effective
  access = tenant membership ∩ role permissions ∩ site/customer/provider
  grants ∩ worker-self authority, per §6.4, covering all seven principal
  types. Not wired into any request handler — deliberately, per "do not
  implement security-sensitive assumptions without approval."
- `docs/tenant-isolation-inventory.md` — every tenant-owned table (all 26
  pre-existing plus 9 new) and every endpoint's current scope enforcement,
  including two gaps for Phase 2 (JSON-embedded scope on two tables can't
  yet carry a VPD predicate) and the disclosed worker-shifts/whoami
  tenant-only gap.
- `tests/test_access_scope.py` (12 tests) and `tests/test_tenant_isolation.py`
  (11 tests) — all new, all passing.

**A real bug found and fixed during the audit, not left for later:** five
endpoints (`runs.py`, `actions.py`, `attendance.py` ×2, `providers.py`)
used `if context.site_ids and X not in context.site_ids`, which skipped
the site check entirely whenever `site_ids` was empty — instead of
denying, exactly the "empty must never mean no filter" anti-pattern §6.4
names directly. A caller presenting only `customer_ids` (legal today)
could reach any site in the tenant. Fixed at all five call sites; the fix
is proven real, not vacuous — I reverted it and confirmed the five new
regression tests fail without it (200/201 instead of the expected 400),
then restored it. Full detail in `docs/tenant-isolation-inventory.md` §3.

**Full suite**: 164 backend tests passing (141 pre-sprint + 12 + 11 new),
including the reverted-then-restored verification above. No console
changes this sprint.

## Design commitments honoured

- **Standalone**: nothing built assumes Prime or Maestro exist — the
  AccessScope resolver takes a `PrincipalContext` from any source; ADR-0009
  confirms Maestro has no separate service in this repo to depend on.
- **Managed authentication, Tempo-owned authorisation**: ADR-0001
  recommends OCI IAM Identity Domains for *authentication*; every grant/
  membership/role table and the resolver itself are Tempo's own schema,
  independent of that choice.
- **Customer-level restriction within 3PL tenants**: designed, not
  switched on. `UserCustomerGrant` exists as its own table, kept distinct
  from `UserProviderGrant` (§6.4's explicit "must not be conflated"), and
  `AccessScope.customer_ids` is independently resolved and tested
  (`test_customer_grants_are_a_distinct_dimension_from_provider_grants`).
  Enforcement is gated on ADR-0007.
- **Read-only first pilot**: `docs/pilot-charter.md` has a five-step
  shadow-to-writeback plan (shadow mode → reconciliation → evaluation →
  staged writeback activation → go/extend/stop), matching PIL-01–PIL-10.

## Outstanding approvals (nothing here blocks starting — see each ADR's "exact work blocked")

| Item | Blocks | Owner |
|---|---|---|
| Repo private + branch protection (P0-01/02) | Nothing built this sprint — flagged as the two Phase 0 items no available tool could execute; needs GitHub web UI / org-admin access | Whoever holds GitHub org admin |
| CODEOWNERS real handles | Required-reviewer enforcement (needs P0-02 too) | Technical lead |
| ADR-0001 (identity provider) | SEC-01/04/15/16, UX-01 (real login) | Technical lead + security |
| ADR-0002 (Oracle topology) | All of Phase 2 | Technical lead + platform owner |
| ADR-0003 (queue tech) | All of Phase 4 | Technical lead |
| ADR-0004 (deployment runtime) | Phase 8 | Technical lead + platform owner |
| ADR-0005 (pilot connectors) | Phase 3 sandbox certification | Product owner + pilot customer |
| ADR-0006 (writeback action) | All of Phase 5 | Product owner + pilot ops owner |
| ADR-0007 (customer security dimension) | Turning on `UserCustomerGrant` enforcement; 3PL customer console access | Product owner + security |
| ADR-0008 (support grant policy) | Any live support-grant issuance | CEO, operations, security |
| ADR-0009 (direct connector vs Maestro) | INT-01's adapter boundary shape | Product owner + technical lead |
| ADR-0010 (VPD scope) | Phase 2's VPD package | Technical lead, DBA, security |
| Pilot customer/site/success measures | Everything in `docs/pilot-charter.md` | CEO + product owner |
| Repo ownership/licensing | Commercial clarity on IP status | CEO + technical lead |

## Updated Phase 1 estimate

The spec's own Phase 1 estimate was 3–5 weeks for the whole phase
(SEC-01 through SEC-24). This sprint completed the parts nothing else in
Phase 1 blocks on:

- **Done**: principal/membership/grant/session/audit schema, the
  AccessScope resolver and its full test coverage, the permission matrix
  consolidation, the tenant-isolation inventory, negative-test baseline,
  and one real cross-cutting bug fix (the empty-site_ids gap) that
  SEC-03's cross-tenant suite would otherwise have had to find later.
- **Not started, and correctly not started**: SEC-01 (real OIDC
  verification — needs ADR-0001), SEC-04 (per-consumer OAuth
  clients/audiences), SEC-05/SEC-06/SEC-07 (kiosk binding, Argon2id
  migration, brute-force controls — none of this sprint touched
  `WorkerCredential`'s existing SHA-256 hashing, a known gap SEC-06 names
  explicitly), SEC-08 (Vault), SEC-09 (rate limits/CORS/headers), SEC-15/16
  (real session issuance — `UserSession` the table exists, nothing writes
  to it yet), SEC-17/18 (cutting real endpoints over to `AccessScope`
  instead of `RequestContext.has_permission`), SEC-19/20 (Oracle VPD — needs
  ADR-0002/0010 and a real Oracle environment), SEC-21 through SEC-24
  (distinct principal issuance, service credentials, async-job scope
  revalidation, the support-grant workflow itself).
- **Revised estimate for the remainder of Phase 1, given the above and
  once ADR-0001/0002 are approved**: roughly 2.5–4 weeks of the original
  3–5, not because scope shrank, but because the schema design,
  resolver logic, and test scaffolding that normally consume the first
  1–1.5 weeks of an identity phase are already built and already passing.
  The real-token-verification path (SEC-01/04/16), Argon2id migration
  (SEC-06), and Oracle VPD (SEC-19/20, its own separate Phase 2
  dependency) remain the long poles — none of them compress just because
  the surrounding contract is ready.

## What deliberately was not done

Per "do not implement security-sensitive assumptions without approval":
no request handler was cut over to `AccessScope`; `X-Tempo-Context` remains
exactly as trusted (or unverified) as before this sprint, except for the
five call sites where the empty-`site_ids` fix changed enforcement of the
*existing* mechanism, not its trust model. No IdP was chosen or
integrated. No kiosk/kiosk-device binding was implemented. No PIN
hash migration (Argon2id) was performed — `WorkerCredential.pin_hash` is
unchanged.
