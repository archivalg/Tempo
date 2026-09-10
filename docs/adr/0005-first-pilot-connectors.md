# ADR-0005: First WMS and workforce connectors

**Status**: Proposed — awaiting approval
**Decision owner**: Product owner and pilot customer (Appendix D: "before Phase 3 build")

## Context

`app/maestro/` already has illustrative clients for a generic WMS
(`app/maestro/wms/client.py`), Deputy, and UKG (Pro WFM and Ready) — all
built against documented vendor APIs but, per this codebase's own
disclosed simplifications, "unverified against a live tenant." INT-05/
INT-06 require certifying one WMS and one workforce connector against a
real sandbox before Phase 3 exit.

## Options considered

The real decision here isn't which *code* to write — it's which *vendor*
the pilot customer actually runs, which this pass has no basis to know.
What can be recommended is the *default assumption* to build the pilot
charter and Phase 3 estimate against, pending the actual customer/site
decision (Appendix D's own separate, commercially-owned item):

1. **Reuse existing Deputy + generic-WMS clients as the working
   assumption** — both already have canonical mapping logic and Maestro
   clients in this repo; the incremental Phase 3 work is sandbox
   certification and hardening (pagination, throttling, real field names),
   not a new integration from scratch.
2. **Assume UKG instead of Deputy** — equally viable code-wise (both exist
   today); the choice is entirely about which vendor the actual pilot
   customer runs, not a technical trade-off this ADR can resolve.
3. **Assume a WMS vendor not yet in this repo** — would require Phase 3 to
   build a new client from zero rather than harden an existing one,
   materially changing the Phase 3 estimate; only relevant once the real
   pilot site is chosen.

## Recommendation

Plan Phase 3 against **the existing generic WMS client + Deputy**, as the
lowest-risk assumption given what's already built and tested — but treat
this as provisional pending the actual pilot customer decision, which is a
prerequisite to Phase 0 exit per the spec's own P0-06 ("define the first
pilot site, source systems..."). Do not begin INT-05/INT-06 sandbox
certification work against this assumption until the pilot charter's
source-system fields (see `docs/pilot-charter.md`) are filled in and
confirmed.

## Trade-offs

- Building the Phase 3 estimate around existing code risks a wasted
  planning cycle if the real customer runs UKG or a different WMS —
  mitigated by treating this as provisional, not by delaying planning
  entirely.
- Certifying against a live sandbox may surface real API differences from
  what the illustrative clients assume (field names, pagination behaviour)
  regardless of which vendor is confirmed — this is expected work, not a
  risk specific to this recommendation.

## Cost

Not separately estimable from Phase 3's own cost (INT-01–INT-12); this ADR
only affects *which* vendor absorbs that cost, not its size, assuming the
confirmed vendor is one already represented in `app/maestro/`.

## Exact work this decision blocks

INT-05 (WMS read connector sandbox certification), INT-06 (Deputy or UKG
read integration sandbox certification), and by extension all of Phase 3's
acceptance criteria (source-parity tests, backfill/incremental sync
verification). Nothing in this sprint depended on this decision.

## Built to be swappable

Not applicable — no connector code was touched this sprint.
