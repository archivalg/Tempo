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

- `services/tempo-api` — the Tempo Optimisation Service. Phases 0, A, B, C
  and D are implemented here (contract foundation; real forecast/MILP/
  CP-SAT solvers; Deputy + UKG Pro WFM + UKG Ready overlay connectors;
  training/leave-RDO/intraday-reallocation models plus WMS backlog
  ingestion; and team composition/3PL margin/scenario planning) — every
  model in the AI Labour Optimisation Spec's catalogue is implemented; see
  its README for details, including the architectural debt the Maestro
  connector layer carries.
- `wiep-mvp.zip`, `wiep_mobile_app_expo.ts` — an earlier proof-of-concept
  scaffold (pre-dates the v2.0 specs). Kept as UI/interaction reference only;
  not the foundation for `services/tempo-api`.

See `docs/roadmap.md` for phase-by-phase status.
