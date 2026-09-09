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
| C — Operational breadth | Intraday reallocation, training/certification, leave/RDO; WMS live backlog integration | **Done** — policy governance, `training_coverage`, `leave_rdo` (both MILP), `intraday_reallocation` (min-cost flow, a new solver family), and WMS backlog ingestion (`app/maestro/wms/`, illustrative since no vendor is named in the spec) all done and tested, including an integration test proving the solver works against connector-ingested data, not just seeded rows | `services/tempo-api/app/solvers/`, `services/tempo-api/app/maestro/wms` |
| D — Enterprise intelligence | Team composition, 3PL cost-to-serve/margin, robust/scenario; restricted finance access | **Done** — `team_composition` and `margin_3pl` (both MILP) and `scenario` (Monte Carlo, analytic per-scenario recourse rather than a re-solved MILP — see `services/tempo-api` README). `margin_3pl` is gated behind `labour.margin.read` on both run creation and read, per §5.2's restricted finance access — the first run_type-specific permission check in this codebase | `services/tempo-api/app/solvers/` |
| E — Controlled action | Action validation, approvals, source staging/writeback, reconciliation | **Done** — §12's two-step contract (`POST /v1/actions/validate` then `POST /v1/actions`), plus a reconciliation endpoint the spec's own acceptance criteria require but doesn't name. `Recommendation` rows are now created (one per completed run) and `ActionRequest` gains the columns validation/execution actually need. The one deliberate, disclosed gap: no real vendor writeback connector exists, so every execution honestly reports `unknown` rather than a fabricated `confirmed` — see `services/tempo-api` README's Phase E section | `services/tempo-api/app/api/v1/actions.py`, `app/maestro/writeback.py` |
| F — Scale and optimisation | Capacity tests, model monitoring, connector catalogue, self-service onboarding | **Not started — next** | — |

## Recommended MVP cut (spec §18.1)

Build Phase 0 + Phase A together, read-only Prime integration, before any
writeback. Phases 0 through E are all done — every model in the AI
Labour Optimisation Spec's ten-model catalogue, every run_type in
Appendix C's enum, and §12's controlled-action pipeline are implemented.
**Phase F is next** (capacity tests, model monitoring, connector
catalogue, self-service onboarding).

## Architectural debt carried from Phase B

Maestro (the connector/canonical-ingestion layer) is architecturally
required to be its own service with its own datastore (spec §17.1's
"Datastore decision"), publishing to Tempo over an API/event boundary. This
codebase keeps `app/maestro/` in-process with Tempo's API and database —
disclosed in `services/tempo-api/README.md`, and kept honest in code by
never importing across the `app/maestro` <-> `app/solvers` boundary. That
now covers four connectors (Deputy, UKG Pro WFM, UKG Ready, WMS), all
sharing one ingestion path (`app/core/ingestion.py`). Splitting it into a
standalone `services/maestro` is a mechanical extraction of that
already-isolated code, not a rewrite, whenever it's warranted (likely
Phase F, or sooner if ingestion volume across these connectors makes
sharing Tempo's process a real bottleneck).

Phase D adds a second, related piece of debt: `scenario`'s Monte Carlo
recourse is computed analytically rather than by re-solving a MILP per
scenario, because this codebase has no async run worker — §18's "heavy
scenario runs return async with progress state" isn't built yet. That's
also Phase F (or sooner) scope: a real async worker would let `scenario`
re-solve the second-stage optimisation per draw instead of approximating it.

Phase E's debt is the sharpest one yet: `app/maestro/writeback.py` has no
real vendor connector at all, by design (§18.1 itself keeps writeback out
of MVP scope absent a named pilot, and there's no live tenant/sandbox to
build one against). Every action currently ends at `unknown` and needs
reconciliation to resolve — not a bug, but a real limitation until a named
pilot with a reversible staging state justifies building one real
connector's write side (most likely candidate: Deputy or UKG Pro WFM,
since those already have real read-side connectors to extend).

## Open decisions this roadmap depends on

The integration spec's §19 (OD-01 to OD-10) lists unresolved architecture
decisions — e.g. canonical DB technology (OD-02), event technology (OD-03),
confidence weights sign-off (OD-08). OD-08 now has a governance *mechanism*
(`app/core/policy.py` — versioned defaults + tenant override), which is a
different thing from the *decision*: the actual weight values are still
code defaults nobody outside this codebase has signed off on. Phase 0's
implementation makes a concrete but reversible default choice for each
open item where one was needed
(documented in `services/tempo-api/README.md`'s "known simplifications"
section) — these are stand-ins, not the actual decisions, which still need
the owners named in the spec.

## Source documents

- `Tempo Product Strategy.docx` — market, positioning, pricing, GTM
- `Tempo Business Specification.docx` — product requirements, MVP criteria
- `Tempo AI Labour Optimisation Spec.docx` — the 10-model solver math (feeds Phase A)
- `Tempo_Prime_AI_Integration_Specification_v2.0.docx` — this roadmap's source
