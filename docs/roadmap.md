# Tempo delivery roadmap

Tracks the phases from `Tempo_Prime_AI_Integration_Specification_v2.0.docx`
§18 against what's actually built, plus what the Product Strategy and
Business Specification call for beyond that spec's backend-only roadmap
(see "Beyond §18" below). Update this file's status column as each phase
lands — it's the single place to check "what's real vs spec" without
re-reading the full integration spec.

| Phase | Scope (§18) | Status | Where |
|---|---|---|---|
| 0 — Contract foundation | Tenant/identity mapping, canonical v1, readiness, run lifecycle, explanation contract, events, audit | **Done** | `services/tempo-api` |
| A — Core Labour Intelligence | Demand forecast, labour requirement, workforce mix, named roster on Tempo-native data | **Done**, with tracked scope reductions (single site/run, fixed shift calendar, skill_code-as-role, static mix availability — see `services/tempo-api` README's "known simplifications") | `services/tempo-api/app/solvers` |
| B — Overlay ingestion | Deputy first; UKG Pro WFM / UKG Ready next; source parity tests | **Done** — Deputy, UKG Pro WFM and UKG Ready, one connector algorithm per vendor with per-product-line clients for UKG. Source parity proven by test (`test_source_parity.py`, parametrized over all three), not just asserted — see `services/tempo-api` README's Phase B section for what's covered vs flagged (full UKG Pro HCM, skill/cert mapping, and webhooks are explicitly out) | `services/tempo-api/app/maestro` |
| C — Operational breadth | Intraday reallocation, training/certification, leave/RDO; WMS live backlog integration | **Done** — policy governance, `training_coverage`, `leave_rdo` (both MILP), `intraday_reallocation` (min-cost flow, a new solver family), and WMS backlog ingestion (`app/maestro/wms/`, illustrative since no vendor is named in the spec) all done and tested, including an integration test proving the solver works against connector-ingested data, not just seeded rows | `services/tempo-api/app/solvers/`, `services/tempo-api/app/maestro/wms` |
| D — Enterprise intelligence | Team composition, 3PL cost-to-serve/margin, robust/scenario; restricted finance access | **Done** — `team_composition` and `margin_3pl` (both MILP) and `scenario` (Monte Carlo, analytic per-scenario recourse rather than a re-solved MILP — see `services/tempo-api` README). `margin_3pl` is gated behind `labour.margin.read` on both run creation and read, per §5.2's restricted finance access — the first run_type-specific permission check in this codebase | `services/tempo-api/app/solvers/` |
| E — Controlled action | Action validation, approvals, source staging/writeback, reconciliation | **Done** — §12's two-step contract (`POST /v1/actions/validate` then `POST /v1/actions`), plus a reconciliation endpoint the spec's own acceptance criteria require but doesn't name. `Recommendation` rows are now created (one per completed run) and `ActionRequest` gains the columns validation/execution actually need. The one deliberate, disclosed gap: no real vendor writeback connector exists, so every execution honestly reports `unknown` rather than a fabricated `confirmed` — see `services/tempo-api` README's Phase E section | `services/tempo-api/app/api/v1/actions.py`, `app/maestro/writeback.py` |
| F — Scale and optimisation | Capacity tests, model monitoring, connector catalogue, self-service onboarding | **Done** — `tests/test_capacity.py` measures real solver wall-clock time at 150 workers x 21 days against §15.1's p95 targets; `app/core/monitoring.py` computes backtest error/drift/solver-gap/version-adoption from run history and publishes `model.drift.detected` on demand; `app/core/connector_catalogue.py` exposes what `app/maestro/` implements over `GET /v1/connectors`; `app/api/v1/onboarding.py` lets a Tenant Admin register a `TenantScope` and a `MaestroConnection` through the API instead of a direct DB insert. See `services/tempo-api` README's Phase F section for what each piece does and doesn't cover — none of these resolve the Maestro-extraction or async-worker debt below, which Phase F's actual scope (§18) never named | `services/tempo-api/app/core/{monitoring,connector_catalogue}.py`, `app/api/v1/{monitoring,onboarding}.py`, `tests/test_capacity.py` |

## Recommended MVP cut (spec §18.1)

Build Phase 0 + Phase A together, read-only Prime integration, before any
writeback. **All six phases §18 names (0 through F) are done** — every
model in the AI Labour Optimisation Spec's ten-model catalogue, every
run_type in Appendix C's enum, §12's controlled-action pipeline, and
Phase F's capacity/monitoring/catalogue/onboarding layer are implemented.
What's left is not a numbered phase: it's the disclosed debt below
(Maestro as a separate service, a real writeback connector, an async run
worker, a credential vault) — each is a specific, scoped piece of work a
production pilot would need, not a "phase" this spec's own roadmap names.

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
already-isolated code, not a rewrite, whenever it's warranted — **still
not done as of Phase F**; Phase F's actual §18 scope (capacity tests,
model monitoring, connector catalogue, self-service onboarding) never
included this extraction, so "every phase is done" does not mean this
debt is resolved. It stays open, likely triggered by ingestion volume
across these connectors making sharing Tempo's process a real bottleneck.

Phase D adds a second, related piece of debt: `scenario`'s Monte Carlo
recourse is computed analytically rather than by re-solving a MILP per
scenario, because this codebase has no async run worker — §18's "heavy
scenario runs return async with progress state" isn't built yet, and
**still isn't after Phase F** (Phase F's monitoring drift-check is
similarly on-demand rather than scheduled, for the same missing-worker
reason — see `services/tempo-api` README's Phase F section). A real async
worker would let `scenario` re-solve the second-stage optimisation per
draw instead of approximating it, and would let drift-check and
`recommendation.expiring` run on a schedule instead of on demand.

Phase E's debt is the sharpest one yet: `app/maestro/writeback.py` has no
real vendor connector at all, by design (§18.1 itself keeps writeback out
of MVP scope absent a named pilot, and there's no live tenant/sandbox to
build one against). Every action currently ends at `unknown` and needs
reconciliation to resolve — not a bug, but a real limitation until a named
pilot with a reversible staging state justifies building one real
connector's write side (most likely candidate: Deputy or UKG Pro WFM,
since those already have real read-side connectors to extend). Phase F's
`MaestroConnection` (self-service onboarding) makes this gap more visible,
not less: a tenant can now register a connection through the API, and it
will sit at `status: pending_credentials` forever until this same
credential-vault-and-real-client gap is closed.

## Beyond §18: the Consumption layer (services/tempo-console)

Everything above tracks the Integration Spec's own six-phase roadmap,
which is entirely backend: contract, solvers, connectors, actions,
enterprise models, and operational maturity. It was never the whole
product. Reviewing the Product Strategy and Business Specification
alongside it surfaced a gap those two documents name directly but §18
doesn't cover at all: the **Consumption layer** (Business Spec §4) — "Prime
AI agents, Tempo's own operational console, or any authorised API client."
Prime's agents and generic API clients were already served by the REST API
itself; **Tempo's own operational console** was not, until now.

`services/tempo-console` — a React/TypeScript SPA — is that console, done
to the same standard as the API: no mocked data, verified end-to-end
against a live backend in a real browser before being called done.
It covers the **Operations Manager** and **Tenant Admin** roles from the
Business Spec's §8 UX roles table (whose stated needs — review AI
recommendations and publish rosters; manage integrations and access — map
directly onto capability the backend already fully implements) and a
partial **Executive** view (dashboard/monitoring). Building it required two
small, honest backend additions (`GET /v1/runs` and `GET /v1/actions` list
endpoints, and `recommendation_id`/`run_type` on `GET /v1/runs/{id}`) — see
`services/tempo-console/README.md` for the full scope and what it
deliberately doesn't cover yet (Worker, Supervisor, Labour Provider — all
three need native Tempo capture on the backend, which doesn't exist; see
below).

## The other gap the same review surfaced: native Tempo capture

The Business Specification (§4/§5) names **Standalone mode** — Tempo's own
PIN/GPS/NFC/biometric clock-in, a Scheduling/Roster Engine, a Performance
Engine — as a first-class deployment path, not a fallback. This codebase
has never built it: every canonical row today comes from either a direct
DB seed (Tempo-native, for tests) or one of the four Overlay connectors
(Deputy, UKG Pro WFM, UKG Ready, WMS). There is no clock-in API. That means
"Standalone" is currently just "not Overlay," not a real, independent
product path — Business Spec §10's requirement that "Tempo must be a
complete, sellable product on its own" isn't met yet for a customer with
no existing T&A system to overlay onto. This is the next candidate gap to
close, tracked here rather than silently left for someone to rediscover.

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
