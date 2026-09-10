# ADR-0004: Deployment runtime

**Status**: Proposed — awaiting approval
**Decision owner**: Technical lead and platform owner (implied by Phase 8's OCI entry criteria; not separately dated in Appendix D)

## Context

A `Dockerfile` exists for `services/tempo-api`; there is no `.github/workflows/`,
no infrastructure-as-code, and no deployment stack at all today. OPS-01–
OPS-04 require production images, IaC-provisioned environments, and CI/CD
with rollback.

## Options considered

1. **OCI Container Instances** — serverless containers, no cluster to
   operate, fastest path to a repeatable environment for a 1-platform-
   engineer team; scales per-container rather than via a shared cluster
   scheduler.
2. **OCI Kubernetes Engine (OKE)** — the standard choice once multiple
   tenants need strong resource/network isolation from each other, or once
   the team needs Kubernetes-native autoscaling, service mesh, or a large
   number of independently-scaled services; materially higher operational
   overhead (cluster upgrades, node pool management, RBAC) than this
   pilot's one-tenant, few-services footprint justifies.
3. **OCI Compute VMs with manual orchestration** — rejected: reintroduces
   exactly the "unmanaged production changes" OPS-02 prohibits.

## Recommendation

**OCI Container Instances** for the pilot (API, workers once Phase 4 lands,
integration service once Phase 3 extracts it, console). Re-evaluate OKE
only if a second pilot tenant is approved with isolation requirements
Container Instances can't meet, or if the number of independently-scaled
services grows enough that a shared scheduler becomes cheaper to operate
than N container instances.

## Trade-offs

- Container Instances' autoscaling and networking primitives are simpler
  than OKE's — appropriate for one tenant, one site, the release
  boundary's own stated scope (§1.2); would need re-evaluation before a
  second pilot site or multi-tenant general availability.
- Some operational tooling (service mesh, advanced canary/blue-green
  patterns) assumes Kubernetes; OPS-04's "immutable artefacts and rollback"
  is achievable on Container Instances via image-tag promotion, just with
  less tooling ecosystem support than an OKE-based CD pipeline would have.

## Cost

Container Instances bills per-container-second with no idle cluster-control-
plane cost, materially cheaper than running an OKE control plane and node
pool sized for headroom at pilot scale. The larger cost is OPS-01–OPS-12's
engineering effort (IaC, CI/CD, monitoring, runbooks), which is comparable
either way.

## Exact work this decision blocks

Phase 8 entirely: OPS-01 (production images), OPS-02 (IaC provisioning),
OPS-04 (CD with rollback), OPS-08 (health checks tuned to the runtime's
deployment model), OPS-09 (autoscaling/resource limits). This sprint's
work does not depend on this decision.

## Built to be swappable

Not applicable — no deployment infrastructure was built this sprint.
