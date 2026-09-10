# ADR-0007: Customer as an enforced security dimension for 3PL deployments

**Status**: Proposed — awaiting approval
**Decision owner**: Product owner and security (Appendix D: "before Phase 1 access model approval")

## Context

`RequestContext.customer_ids` already exists and is already enforced on
several endpoints (e.g. `app/api/v1/runs.py`'s scope checks) — but only as
an ad hoc filter, not as a first-class principal-level security dimension
with its own grant/membership model the way the production-readiness
spec's §6.2/§6.4 describe ("Customer user... Customer grant intersected
with tenant and site grants... 3PL customer reporting and approvals").
§6.4 is explicit that "Customer remains a security dimension for 3PL
customer users. Provider remains a separate security dimension for
labour-hire users. These dimensions must not be conflated."

## Options considered

1. **Yes — make it a first-class, enforced grant dimension.** A customer
   user's access is the intersection of tenant membership, role
   permissions, and an explicit `UserCustomerGrant` set — structurally
   identical to how this sprint already built `UserProviderGrant` for the
   Labour Provider role, just for the customer side of a 3PL tenant.
2. **No — keep `customer_ids` as a caller-supplied filter only,** as today.
   Simpler short-term, but leaves exactly the gap SEC-02/SEC-18 exist to
   close: a filter a caller can widen or omit is not an authority boundary,
   it's a request parameter. A 3PL customer user given console access
   under this model could, if the console UI let them, request another
   customer's data and have the backend treat "no customer_ids supplied"
   as "show tenant-wide," which `app/dependencies.py`'s own DP-08 rule
   already says must never happen for *tenant* scope — the same logic
   applies to customer scope once real customer users exist.

## Recommendation

**Yes.** Treat customer exactly the way this sprint already treats
provider: a distinct grant table (`UserCustomerGrant`), intersected into
`AccessScope.customer_ids` the same way `UserProviderGrant` intersects
into `AccessScope.provider_id`. This is already how
`app/core/access_scope.py` is written this sprint — the resolver already
keeps customer and provider as separate fields (per §6.4's explicit
instruction not to conflate them) — so approving this ADR does not require
new design, only turning on enforcement of a dimension the contract
already models.

## Trade-offs

- Requires 3PL customer users to actually exist as a principal type with
  real grants before a customer-facing console view is meaningful — there
  is no 3PL customer-facing UI in the console today (`services/tempo-console`
  has no such page), so approving this ADR creates a Phase 7 UI backlog
  item, not just a backend one.
- If declined, `customer_ids` stays a request-supplied filter — workable
  for the pilot's operations-manager-only console usage, but must be
  revisited before any 3PL customer is given direct console access, per
  SEC-18's IDOR-tampering requirement.

## Cost

Low incremental engineering cost given this sprint's design already
carries the field — the remaining work is (a) populating real
`UserCustomerGrant` rows once real 3PL customer users are provisioned, and
(b) a console customer-reporting view (Phase 7, and only "unless selected
for the pilot" per that phase's own exclusions).

## Exact work this decision blocks

Turning on `UserCustomerGrant`-based enforcement in the AccessScope
resolver's default behaviour (today it's modelled but not yet wired to any
real endpoint — see `app/core/access_scope.py`'s own docstring); any
console work exposing customer-scoped views to a 3PL customer user; the
"Customer user" row of §6.2's principal table becoming real rather than
theoretical.

## Built to be swappable

This is the one ADR this sprint's code is most directly staged for: `docs/tenant-isolation-inventory.md`
records `customer_id` as an inconsistently-enforced filter today, and
`app/core/access_scope.py`'s `AccessScope.customer_ids` field exists and is
tested (see `tests/test_access_scope.py`) independently of whether this
ADR is approved — approval only changes whether real grant rows are
populated and whether endpoints are switched to require it.
