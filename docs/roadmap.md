# Tempo delivery roadmap

Tracks the phases from `Tempo_Prime_AI_Integration_Specification_v2.0.docx`
§18 against what's actually built. Update this file's status column as each
phase lands — it's the single place to check "what's real vs spec" without
re-reading the full integration spec.

| Phase | Scope (§18) | Status | Where |
|---|---|---|---|
| 0 — Contract foundation | Tenant/identity mapping, canonical v1, readiness, run lifecycle, explanation contract, events, audit | **Done** | `services/tempo-api` |
| A — Core Labour Intelligence | Demand forecast, labour requirement, workforce mix, named roster on Tempo-native data | **Done**, with tracked scope reductions (single site/run, fixed shift calendar, skill_code-as-role, static mix availability — see `services/tempo-api` README's "known simplifications") | `services/tempo-api/app/solvers` |
| B — Overlay ingestion | Deputy first; UKG Pro WFM / UKG Ready next; source parity tests | **Done** — Deputy, UKG Pro WFM and UKG Ready, one connector algorithm per vendor with per-product-line clients for UKG. Source parity proven by test (`test_source_parity.py`, parametrized over all three), not just asserted — see `services/tempo-api` README's Phase B section for what's covered vs flagged (full UKG Pro HCM, skill/cert mapping, and webhooks are explicitly out) | `services/tempo-api/app/maestro` |
| C — Operational breadth | Intraday reallocation, training/certification, leave/RDO; WMS live backlog integration | Not started | — |
| D — Enterprise intelligence | Team composition, 3PL cost-to-serve/margin, robust/scenario; restricted finance access | Not started | — |
| E — Controlled action | Action validation, approvals, source staging/writeback, reconciliation | Not started — `ActionRequest` table exists in Phase 0's schema so this doesn't need a breaking migration later, but no endpoints | — |
| F — Scale and optimisation | Capacity tests, model monitoring, connector catalogue, self-service onboarding | Not started | — |

## Recommended MVP cut (spec §18.1)

Build Phase 0 + Phase A together, read-only Prime integration, before any
writeback. Phases 0, A and B are done; **Phase C is next** (intraday
reallocation, training/certification, leave/RDO, WMS live backlog
integration).

## Architectural debt carried from Phase B

Maestro (the connector/canonical-ingestion layer) is architecturally
required to be its own service with its own datastore (spec §17.1's
"Datastore decision"), publishing to Tempo over an API/event boundary. This
codebase keeps `app/maestro/` in-process with Tempo's API and database —
disclosed in `services/tempo-api/README.md`, and kept honest in code by
never importing across the `app/maestro` <-> `app/solvers` boundary. That
now covers three connectors (Deputy, UKG Pro WFM, UKG Ready), all sharing
one ingestion path (`app/core/ingestion.py`). Splitting it into a
standalone `services/maestro` is a mechanical extraction of that
already-isolated code, not a rewrite, whenever it's warranted (likely
Phase F, or sooner if ingestion volume across these connectors makes
sharing Tempo's process a real bottleneck).

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
