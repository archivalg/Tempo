# Tempo

AI-native labour optimisation engine for warehousing and 3PL operations —
runs standalone or as an overlay on a customer's existing Kronos/UKG or
Deputy deployment, and as the labour-domain backend for Prime AI's Labour
Intelligence pack.

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
  Spec's catalogue is implemented. See its README for details, including
  the disclosed debt that remains regardless (Maestro as a separate
  service, a real vendor writeback connector, an async run worker, a
  credential vault) — these are specific, scoped gaps a production pilot
  would need to close next, not unfinished phases.
- `services/tempo-console` — the Real-Time Operations Console (Business
  Specification §4/§8), the first UI in this codebase. Covers Operations
  Manager (review AI recommendations, publish rosters via the §12 action
  pipeline) and Tenant Admin (self-service onboarding); Worker, Supervisor
  and Labour Provider are out of scope until native Tempo capture exists
  on the backend — see its README for what's covered and why.
- `wiep-mvp.zip`, `wiep_mobile_app_expo.ts` — an earlier proof-of-concept
  scaffold (pre-dates the v2.0 specs). Kept as UI/interaction reference only;
  not the foundation for `services/tempo-api` or `services/tempo-console`.

See `docs/roadmap.md` for phase-by-phase status.
