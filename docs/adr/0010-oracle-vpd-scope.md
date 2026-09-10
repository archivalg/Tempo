# ADR-0010: Oracle VPD scope beyond tenant

**Status**: Proposed — awaiting approval
**Decision owner**: Technical lead, DBA, security (Appendix D: "before Phase 2 migration design")

## Context

§6.5 requires Oracle VPD (`DBMS_RLS`) as an independent containment layer
beneath the application's own tenant predicates: "VPD policies must fail
closed when application context is missing, malformed or stale... Direct
SQL using the runtime account must still be unable to return another
tenant's rows." §6.5 also asks whether VPD should extend to "finite site or
customer scope" beyond tenant, "where justified."

## Options considered

1. **Tenant-only VPD.** Every tenant-owned table gets a `DBMS_RLS` policy
   keyed on `tenant_id` via the request-local Oracle application context.
   Simplest to build and reason about; matches this sprint's
   tenant-isolation inventory finding that `tenant_id` is already present
   and filtered-on for every canonical table today (the gap is *trust*,
   not *coverage* — see `docs/tenant-isolation-inventory.md`).
2. **Tenant + site VPD.** Adds a second policy predicate for
   high-risk tables (`ShiftAssignment`, `AttendanceSession`, `Worker`)
   scoped to the caller's finite authorised site set — closer to SEC-19's
   literal text ("Every tenant-owned table must carry tenant_id. High-risk
   site, customer, provider, worker and run records must also carry the
   applicable subordinate boundary columns").
3. **Tenant + site + customer + provider VPD.** Full defense-in-depth
   matching every `AccessScope` dimension this sprint's resolver models;
   materially more DBMS_RLS policies to design, test, and keep in sync with
   applicaton-layer grant changes.

## Recommendation

**Tenant + site VPD** for this pilot (option 2). Defer customer/provider
VPD to a follow-up once ADR-0007 (customer as an enforced dimension) is
approved and in production use — adding VPD policies for a dimension not
yet backed by real grant data (no 3PL customer users exist yet) would be
premature hardening with nothing real to test it against.

## Trade-offs

- Customer and provider isolation remain application-layer-only (via
  `AccessScope`) until the follow-up lands — acceptable for a pilot with
  one tenant and no live 3PL customer users yet, not acceptable indefinitely
  once ADR-0007 is exercised in production.
- Site-level VPD requires the application context to carry the caller's
  *finite* site set (not "all sites"), which is exactly what
  `AccessScope.site_ids` (built this sprint) is designed to resolve to —
  §6.4's "all sites... must resolve to the current finite authorised set...
  never mean no filter" requirement is already encoded in the contract,
  independent of whether VPD is later layered under it.

## Cost

Each additional VPD dimension is roughly proportional DBA/security design
and testing effort (SEC-19's "non-owner real-database isolation tests" per
dimension); scoping to tenant + site keeps Phase 2's VPD package to the two
dimensions this pilot's actual data (one tenant, multiple sites, no live
customer/provider principals yet) can meaningfully exercise.

## Exact work this decision blocks

DAT-05 (index/partitioning decisions, which should account for the VPD
predicate columns) and SEC-19/SEC-20's Oracle policy package design in
Phase 2. Nothing in this sprint depended on this decision — the identity
models and AccessScope resolver are Oracle-topology-independent.

## Built to be swappable

`docs/tenant-isolation-inventory.md` records site/customer/provider column
presence per table today, giving Phase 2 a ready-made list of which tables
need a second VPD predicate under this recommendation without re-auditing
the codebase from scratch.
