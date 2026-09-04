# Tempo delivery roadmap

Tracks the phases from `Tempo_Prime_AI_Integration_Specification_v2.0.docx`
§18 against what's actually built. Update this file's status column as each
phase lands — it's the single place to check "what's real vs spec" without
re-reading the full integration spec.

| Phase | Scope (§18) | Status | Where |
|---|---|---|---|
| 0 — Contract foundation | Tenant/identity mapping, canonical v1, readiness, run lifecycle, explanation contract, events, audit | **Done** | `services/tempo-api` |
| A — Core Labour Intelligence | Demand forecast, labour requirement, workforce mix, named roster on Tempo-native data | **Not started** — Phase 0 stubs the four endpoints; real solver logic (GBM forecast, MILP mix, CP-SAT roster per AI Labour Optimisation Spec §3) is the next milestone | — |
| B — Overlay ingestion | Deputy first; UKG Pro WFM / UKG Ready next; source parity tests | Not started | — |
| C — Operational breadth | Intraday reallocation, training/certification, leave/RDO; WMS live backlog integration | Not started | — |
| D — Enterprise intelligence | Team composition, 3PL cost-to-serve/margin, robust/scenario; restricted finance access | Not started | — |
| E — Controlled action | Action validation, approvals, source staging/writeback, reconciliation | Not started — `ActionRequest` table exists in Phase 0's schema so this doesn't need a breaking migration later, but no endpoints | — |
| F — Scale and optimisation | Capacity tests, model monitoring, connector catalogue, self-service onboarding | Not started | — |

## Recommended MVP cut (spec §18.1)

Build Phase 0 + Phase A together, read-only Prime integration, before any
writeback. Phase 0 is done; **Phase A is next**.

## Open decisions this roadmap depends on

The integration spec's §19 (OD-01 to OD-10) lists unresolved architecture
decisions — e.g. canonical DB technology (OD-02), event technology (OD-03),
confidence weights sign-off (OD-08). Phase 0's implementation makes a
concrete but reversible default choice for each where one was needed
(documented in `services/tempo-api/README.md`'s "known simplifications"
section) — these are stand-ins, not the actual decisions, which still need
the owners named in the spec.

## Source documents

- `Tempo Product Strategy.docx` — market, positioning, pricing, GTM
- `Tempo Business Specification.docx` — product requirements, MVP criteria
- `Tempo AI Labour Optimisation Spec.docx` — the 10-model solver math (feeds Phase A)
- `Tempo_Prime_AI_Integration_Specification_v2.0.docx` — this roadmap's source
