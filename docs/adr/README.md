# Architecture Decision Records

Drafted during the Phase 0 mobilisation sprint (P0-05: "Create a decision
record for identity provider, Oracle topology, queue technology, deployment
runtime and first pilot connectors"), plus the additional decisions
Appendix D of `Tempo_Production_Readiness_Implementation_Specification_v1.1.docx`
lists as blocking Phase 1 and later work.

Each ADR is a **recommendation for approval**, not a decision already made —
per the production-readiness spec's own governance model, these need a named
owner's sign-off (see each ADR's "Decision owner" line, taken from Appendix
D) before the work it unblocks may start. Nothing in this repository has
been built on the assumption that an unapproved recommendation here is
correct — where engineering work in this sprint needed to proceed before an
ADR is approved, it was built to be swappable (see each affected ADR's
"Built to be swappable" note) rather than by silently picking an answer.

| # | Decision | Recommendation | Owner (Appendix D) | Blocks |
|---|---|---|---|---|
| [0001](0001-identity-provider.md) | Identity provider adapter | OCI IAM Identity Domains (OIDC), local-account fallback for small customers | Technical lead + security | All of Phase 1's token verification, login, session work |
| [0002](0002-oracle-topology.md) | Oracle topology & recovery targets | Autonomous Database, single region, 15 min RPO / 4 hr RTO to match the spec's own pilot NFRs | Technical lead + platform owner | Phase 2 entirely (migrations, pooling, VPD) |
| [0003](0003-queue-technology.md) | Queue / event technology | OCI Queue for commands, OCI Streaming (or a transactional outbox + polling if Streaming is unavailable in-region) for events | Technical lead | Phase 4 entirely (async workers, scheduler, outbox) |
| [0004](0004-deployment-runtime.md) | Deployment runtime | OCI Container Instances for pilot scale; re-evaluate OKE only if a second tenant needs isolation guarantees CI can't give | Technical lead + platform owner | Phase 8 (CI/CD, images, autoscaling) |
| [0005](0005-first-pilot-connectors.md) | First WMS + workforce connectors | Reuse existing illustrative WMS client + Deputy (both already have Maestro clients in this repo); confirm against real sandboxes before Phase 3 build | Product owner + pilot customer | Phase 3 (INT-05/INT-06 sandbox certification) |
| [0006](0006-first-writeback-action.md) | First writeback action & reversal method | `publish_roster` against Deputy, reversal = re-publish the prior committed roster version (no vendor-side "undo" assumed) | Product owner + pilot operations owner | Phase 5 entirely |
| [0007](0007-customer-security-dimension.md) | Customer as an enforced security dimension | Yes — enforce it; it's already a first-class grant in the AccessScope design built this sprint, just not switched on for runtime enforcement yet | Product owner + security | Turning on `UserCustomerGrant` enforcement in Phase 1; 3PL customer-user console access |
| [0008](0008-privileged-support-grant-policy.md) | Privileged support grant & step-up policy | Time-bound grant (max 8h), step-up via re-authentication, mandatory reason + immutable audit event | CEO, operations, security | SEC-24, the support-operator principal type, break-glass procedure |
| [0009](0009-direct-connector-vs-maestro.md) | Tempo direct connector vs. Maestro adapter, per integration | Direct Tempo connector for the pilot (Maestro has no code in this repo to extend); revisit if/when a customer requires Maestro-brokered access | Product owner + technical lead | Phase 3's adapter boundary shape |
| [0010](0010-oracle-vpd-scope.md) | Oracle VPD scope beyond tenant | Tenant + site; customer/provider VPD deferred to a follow-up once 0007 lands in practice | Technical lead, DBA, security | Phase 2's VPD policy package (DAT-05, SEC-19) |

Two Appendix D decisions are deliberately not ADRs here: **repository
ownership/licensing** and **first pilot customer, site and success
measures** are commercial/executive decisions this pass has no technical
basis to recommend a specific answer for. They still block Phase 0 exit —
see the pilot charter (`docs/pilot-charter.md`) for what's templated and
waiting on them.
