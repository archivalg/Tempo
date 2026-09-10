# ADR-0009: Tempo direct connector vs. Maestro adapter, per pilot integration

**Status**: Proposed — awaiting approval
**Decision owner**: Product owner and technical lead (Appendix D: "before Phase 3 build")

## Context

Per earlier research in this engagement, **Maestro has no separate
service or repository** — it's a named architectural role in the
Integration Specification, and this codebase's own `app/maestro/` is
explicitly disclosed debt: connector code that *should* be its own
service with its own datastore, currently living in-process with Tempo.
The production-readiness spec is careful throughout to make Maestro
*optional*: "Tempo's integration runtime or Maestro acquires, maps,
validates and replays source data," never *only* Maestro. INT-01 requires
"an adapter boundary through which Maestro may publish the same canonical
contracts without becoming mandatory."

## Options considered

1. **Tempo direct connector for the pilot** — extract `app/maestro/`'s
   existing connector code into its own deployable Tempo integration
   service (INT-01), without introducing an actual separate Maestro
   product/team/codebase that doesn't exist today.
2. **Wait for/commission a real Maestro service before Phase 3** — there is
   no such service to integrate with; building one from scratch would be
   materially larger scope than this pilot's release boundary (§1.2: "one
   WMS integration, one workforce-management integration") justifies, and
   contradicts SEC-13/§6.1's requirement that Tempo work standalone.

## Recommendation

**Tempo direct connector** for both the pilot WMS and workforce
integrations. Define the adapter *contract* (INT-02's versioned canonical
ingestion API/event shape) so that a real Maestro service, if one is
built later, can publish through the same contract — but do not block or
resource this pilot on Maestro's existence.

## Trade-offs

- Defers the "Maestro as separate service" architectural debt this
  codebase has carried since Phase B rather than resolving it now — an
  explicit, disclosed trade-off consistent with the spec's own
  Phase-3-scoped exclusion ("Additional WMS or WFM products" and
  "Bidirectional writeback" are excluded from Phase 3, not extraction of
  Maestro itself, but the same "narrow first release" logic applies).
- If a future customer specifically requires Maestro-brokered integration
  (e.g., they already run Maestro for other systems), the adapter-contract
  design this ADR asks for should make that a matter of pointing a new
  publisher at the existing ingestion contract, not a Tempo-side rewrite —
  worth validating against INT-02's actual contract design once written,
  not assumed here.

## Cost

No additional cost versus Phase 3's own scope (INT-01–INT-12) — this ADR
resolves *which* runtime does the work Phase 3 already requires, not new
work on top of it.

## Exact work this decision blocks

INT-01's own acceptance criterion (a defined adapter boundary) and the
shape of INT-02's canonical ingestion contract — whether it's designed
API-first (a real Maestro publisher could call it) or event-first only.
Nothing in this sprint depended on this decision.

## Built to be swappable

Not applicable — no connector/integration-service code was touched this
sprint.
