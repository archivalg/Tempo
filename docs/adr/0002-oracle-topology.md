# ADR-0002: Oracle topology and recovery targets

**Status**: Proposed — awaiting approval
**Decision owner**: Technical lead and platform owner (Appendix D: "before Phase 2 build")

## Context

`services/tempo-api` defaults to SQLite with `Base.metadata.create_all` —
fine for tests, not for a production database. The spec's §17.1 target is
Oracle Autonomous Database; DAT-01/02 require validating every SQLAlchemy
mapping against it and replacing schema-on-boot with Alembic migrations.
Cross-phase NFRs (§15) propose a 15-minute recovery point and a 4-hour
recovery time for the pilot.

## Options considered

1. **Oracle Autonomous Database (ADB), single region** — matches the spec's
   named target exactly; managed backups, patching, and scaling; simplest
   operationally for a 1-FTE platform engineer.
2. **Oracle ADB, multi-region active-active** — exceeds the spec's own
   explicit Phase 8 exclusion ("active-active multi-region operation unless
   separately approved") and this pilot's one-warehouse scope; unjustified
   cost and complexity for a single-site pilot.
3. **Self-managed Oracle on OCI Compute** — full control over tuning, no
   ADB feature gaps; adds patching/backup/HA engineering this team doesn't
   have spare capacity for, and contradicts the "managed platform" delivery
   principle implicit in choosing Autonomous Database at all.
4. **A non-Oracle database (Postgres) instead** — cheaper and what this
   codebase's own tests already run against; rejected as an ADR outcome
   because the spec names Oracle as the production target throughout (VPD/
   DBMS_RLS in particular, §6.5, has no equivalent story here) — raising it
   only as a cost/timeline trade-off worth the technical lead's attention,
   not a recommendation.

## Recommendation

**Oracle Autonomous Database, single region**, sized for the pilot's one
warehouse, with automated backups and a documented restoration runbook
targeting the spec's own proposed NFRs: **15-minute recovery point, 4-hour
recovery time** (§15's cross-phase targets, adopted here rather than
invented separately).

## Trade-offs

- Single region means a regional OCI outage takes Tempo down for the
  pilot's duration — accepted, matching the spec's explicit Phase 8
  exclusion of active-active operation "before commercial demand requires
  it."
- ADB's workload-specific tuning knobs are narrower than a self-managed
  instance; acceptable at pilot data volumes (one warehouse, one WMS, one
  workforce system).
- Locks the codebase into validating against Oracle-specific SQL/driver
  behaviour (DAT-01) rather than staying database-agnostic — a real cost
  if a future customer needs a non-Oracle deployment, not a concern for
  this pilot.

## Cost

Oracle ADB has a genuinely free tier (Always Free) that likely covers
pilot-scale data; beyond that, ADB pricing is consumption-based (OCPU +
storage), materially cheaper than provisioning a comparable self-managed
HA Oracle instance in engineer-hours alone. The 15-minute-RPO/4-hour-RTO
targets are the *proposed* pilot minimums from §15 — tightening either
needs capacity and cost validation the spec itself flags as a prerequisite
to any tighter contractual SLA.

## Exact work this decision blocks

All of Phase 2: DAT-01 (driver/mapping validation), DAT-02 (Alembic),
DAT-03 (schema separation), DAT-04 (pooling/retry/timeout tuning), DAT-05
(index/partition design), DAT-09 (backup/restore). None of this sprint's
Phase 1 work (identity/membership models, AccessScope) depends on this
decision — those models are written against the existing SQLAlchemy/SQLite
setup and will migrate the same way every other table in this codebase
migrates once Alembic lands.

## Built to be swappable

Not applicable here — this sprint added no database-topology-specific
code. The new identity tables (`app/models/identity.py`) use the same
plain `String`/`DateTime(timezone=True)` column types as every existing
canonical table, so they carry no SQLite-specific assumption to unwind.
