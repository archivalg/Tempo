# ADR-0001: Identity provider adapter

**Status**: Proposed — awaiting approval
**Decision owner**: Technical lead and security (Appendix D: "before Phase 1 build")

## Context

Every request today authenticates via `X-Tempo-Context`, a client-supplied
JSON header trusted with zero verification (`app/dependencies.py`). This is
explicitly documented as "a Phase 0 stand-in, not a security control, and
must not reach production." The production-readiness spec's §6.3 requires
"a managed OIDC provider for authentication," short-lived audience-bound
access tokens, and rotating refresh sessions in Secure/HttpOnly cookies.
Tempo must remain independently deployable — SEC-13 requires it to
authenticate, authorise, and administer tenants with Prime and Maestro both
unavailable.

## Options considered

1. **OCI IAM Identity Domains** — native to the spec's own reference
   deployment (§6.3 names it first), standards-based OIDC, supports
   federation to a customer's own IdP (Entra ID, Google, etc.) without
   Tempo needing separate adapters per customer.
2. **Auth0 / Okta** — mature, well-documented OIDC providers with broad
   enterprise-federation support; adds a vendor dependency and cost outside
   the OCI estate the rest of the platform targets.
3. **Self-hosted Keycloak** — no per-seat licensing, full control; adds an
   operational burden (patching, HA, backup) this team does not yet have
   spare capacity for per the delivery plan's staffing (1 platform
   engineer covering OCI, CI/CD, Vault, monitoring *and* recovery).
4. **Build a minimal Tempo-hosted token issuer** — rejected outright: SEC-01
   /SEC-16 require real OIDC (issuer/audience/signature/expiry/key-rotation
   verification against a real IdP), and the spec's own text never
   contemplates Tempo issuing its own identity tokens from scratch; the
   token-*validation* work is Tempo's, not token *issuance*.

## Recommendation

**OCI IAM Identity Domains**, with local accounts as a documented fallback
for a small customer that has no enterprise IdP of its own (spec §6.3
explicitly allows this, with a required adaptive password hash and
mandatory admin MFA).

## Trade-offs

- Ties Tempo's auth stack to OCI, consistent with the rest of the platform
  target (Oracle ADB, OCI compute) — a deliberate reduction in portability
  in exchange for one fewer vendor relationship and one fewer set of
  operational runbooks.
- OCI IAM Identity Domains' federation-adapter maturity for less-common
  enterprise IdPs is less battle-tested than Auth0/Okta's; the pilot's one
  named customer needs to be checked against OCI IAM's supported federation
  list before this is locked in.
- Local-account fallback adds a password-reset/MFA-enrollment flow the
  console doesn't have yet (Phase 7, UX-01).

## Cost

Primarily engineering time, not licence cost at pilot scale (OCI IAM
Identity Domains' free tier covers a low user count comfortably). The real
cost is the Phase 1 build itself (SEC-01/02/04/15/16), not the provider
choice — switching providers later mainly means re-pointing JWKS/issuer
config and re-testing SEC-01's token verification suite, *if* the
AccessScope contract (this sprint's deliverable) stays the seam between
"a token was verified" and "what can this principal do" — which it does.

## Exact work this decision blocks

Nothing built this sprint depends on this decision (see
`app/core/access_scope.py`'s docstring — it's built to accept an
already-verified principal from any source). What's blocked until this is
approved:
- SEC-01 (OIDC token verification middleware) — needs a real issuer/JWKS
  endpoint to test against.
- SEC-04 (separate OAuth clients/audiences per consumer).
- SEC-15/SEC-16 (session architecture, asymmetric signing, Prime token
  exchange).
- UX-01 (console login flow) — needs a real authorization endpoint to
  redirect to.

## Built to be swappable

`app/core/access_scope.py`'s `resolve_access_scope()` takes a
`PrincipalContext` — tenant/user/roles/grants already resolved — and never
imports or references a specific IdP. The as-yet-unbuilt piece is the
adapter that turns a verified JWT's claims into a `PrincipalContext`; that
adapter is the only code this decision actually gates.
