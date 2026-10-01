# Tempo

AI-native labour optimisation engine for warehousing and 3PL operations —
runs standalone or as an overlay on a customer's existing Kronos/UKG or
Deputy deployment, and as the labour-domain backend for Prime AI's Labour
Intelligence pack.

## Start here

- `docs/roadmap.md` — the delivery plan and milestone status (what is open, partial, blocked or accepted).
- `docs/DEPLOYMENT.md` — what is running now: revision, ports, migration head, how to deploy and verify.
- `docs/build-progress.md` — the historical build ledger (evidence per feature; stale statements are marked).
- Checks: `scripts/smoke.sh` (read-only smoke test of a running Tempo), `scripts/e2e.sh` (browser tests on the throw-away `tempo_e2e` database), GitHub CI in `.github/workflows/ci.yml`.

## Documents

- `Tempo Product Strategy.docx` — market, positioning, pricing, GTM
- `Tempo Business Specification.docx` — product requirements, MVP criteria
- `Tempo AI Labour Optimisation Spec.docx` — the 10-model solver math
- `Tempo_Prime_AI_Integration_Specification_v2.0.docx` — build-grade integration contract with Prime AI/Maestro

## Code

- `services/tempo-api` — the Tempo Optimisation Service. All six phases
  §18 names (0 through F) are implemented here: contract foundation; real
  forecast/MILP/CP-SAT solvers; Deputy + UKG Pro WFM + UKG Ready overlay
  connectors; training/leave-RDO/intraday-reallocation models plus WMS
  backlog ingestion; team composition/3PL margin/scenario planning; the
  §12 controlled-action pipeline (validate, approve, writeback, reconcile);
  and capacity tests, model monitoring, a connector catalogue, and
  self-service onboarding. Every model in the AI Labour Optimisation
  Spec's catalogue is implemented. Beyond §18, it also implements
  Standalone mode's native capture (Business Spec §4/§5) — PIN/NFC
  clock-in/out with optional GPS geofencing, and a real (not stubbed)
  native writeback path that publishes rosters and approves leave directly
  against Tempo's own canonical tables, no vendor connector needed. See
  its README for details, including the disclosed debt that remains
  regardless (Maestro as a separate service, a real *Overlay* vendor
  writeback connector, an async run worker, a credential vault) — these
  are specific, scoped gaps a production pilot would need to close next,
  not unfinished phases.
- `services/tempo-console` — the Real-Time Operations Console (Business
  Specification §4/§8), the first UI in this codebase. Covers Operations
  Manager (review AI recommendations, publish rosters via the §12 action
  pipeline) and Tenant Admin (self-service onboarding); Worker, Supervisor
  and Labour Provider views are the natural next step now that native
  Tempo capture exists on the backend — see its README for what's covered
  and why.
- `wiep-mvp.zip`, `wiep_mobile_app_expo.ts` — an earlier proof-of-concept
  scaffold (pre-dates the v2.0 specs). Kept as UI/interaction reference only;
  not the foundation for `services/tempo-api` or `services/tempo-console`.

See `docs/roadmap.md` for phase-by-phase status.
