# Tempo Optimisation Service — Phase 0 + Phase A

A FastAPI implementation of the contract foundation (Phase 0) and the four
core Labour Intelligence models (Phase A) from
`Tempo_Prime_AI_Integration_Specification_v2.0.docx` (§18): Phase 0's exit
outcome — *"Prime can call a stubbed Tempo run end-to-end with governed
evidence"* — plus Phase A's — demand forecast, labour requirement,
workforce mix, and named roster running on Tempo-native data.

This is not the WIEP MVP scaffold (`wiep-mvp.zip` at the repo root) — that
was a UI/heuristic proof of concept with no tenancy, versioning, or run
lifecycle. This service replaces it as the foundation going forward; the
scaffold is kept only as UI/interaction reference. See `docs/roadmap.md` at
the repo root for the full phase plan.

## What's implemented

Phase 0 — the contract foundation every later phase depends on:

| Spec section | Implemented as |
|---|---|
| §5 Identity, tenancy and entitlements | `app/schemas/tenancy.py`, `app/dependencies.py` — every request must carry an explicit, non-defaultable scope |
| §6 Canonical data model | `app/models/canonical.py` (entities), `app/schemas/envelope.py` (§6.2 ingestion envelope) |
| §7.3 Readiness API | `app/api/v1/readiness.py` |
| §8 Run contracts | `app/schemas/runs.py`, `app/api/v1/runs.py` |
| §10 Run orchestration and lifecycle | `app/core/lifecycle.py` — the state graph is transcribed from §10's table |
| §11 Explainability and governed evidence | `app/core/confidence.py`, the `Explanation` schema in `app/schemas/runs.py` |
| §13 Events | `app/core/events.py` — outbox-backed, in-process delivery for now |
| §14.2 Audit record | `app/core/audit.py` |
| §8.6 / Appendix B Error contract | `app/errors.py` |

Phase A — real solvers reading real canonical data, in `app/solvers/`:

| Run type | Model | Method | AI Labour Optimisation Spec |
|---|---|---|---|
| `demand_forecast` | Holt linear (double exponential smoothing) | statistical | §3.1 / Appendix A.1 |
| `labour_requirement` | Forecast → hours translation via WorkStandard + ActivityRoleZoneMap | deterministic | §3.2 / Appendix A.2 |
| `workforce_mix` | Headcount mix by labour source type | MILP (OR-Tools CBC) | §3.3 / Appendix A.3 |
| `named_roster` | Named worker-to-shift assignment | CP-SAT (OR-Tools) | §3.4 / Appendix A.4 |

The four models chain: named_roster calls workforce_mix for its headcount
targets, workforce_mix calls labour_requirement for its hours, and
labour_requirement calls demand_forecast for its volumes — matching the
spec's own pipeline (Strategy doc §4). Every other `run_type` in Appendix C
is still a legal request that returns `TEMPO-RUN-004` rather than a 404, so
Prime's tool schema doesn't need to change as later phases land.

## Known simplifications (tracked, not hidden)

Phase 0:
- **Identity**: §5.3 specifies OIDC/OAuth2 JWTs between Prime, Tempo and
  Maestro. Standing up a real IdP is out of scope here — callers instead
  present an already-validated scope via an `X-Tempo-Context` header. This
  is a stand-in for a token verifier, not a security control, and must not
  reach a production/pilot environment (tracked as OD-01 in the spec).
- **Canonical ingestion**: there's no real Maestro connector yet (that's
  Phase B). Populate the canonical tables via direct inserts or a seed
  script during testing — see `tests/factories.py` for a worked example.
- **Idempotency store and event bus** are in-process — fine for one API
  replica, not for Phase F scale.
- **Database**: SQLite by default (`TEMPO_DATABASE_URL` env var to
  override). Production target is Oracle Autonomous Database per spec
  §17.1; swapping the URL is enough at this layer since there's no
  Oracle-specific SQL here, but this hasn't been validated against ADB.

Phase A (each solver module's own docstring has the full list):
- **Single site per run** — `request.scope.site_ids` must resolve to one
  warehouse; multi-site optimisation isn't modelled yet.
- **Fixed two-shift calendar** (`app/solvers/shifts.py`) rather than a
  per-tenant configured one — no canonical entity defines shift types yet.
- **Role/zone eligibility** comes from `SkillCertification.skill_code`
  doubling as a role name — there's no dedicated role-assignment entity.
- **Workforce Mix's availability pool is static** for the whole planning
  window (day-level absence is Named Roster's job, via `Availability`).
- **Productivity/performance multipliers are fixed at 1.0** — no
  per-worker productivity data is modelled yet.
- **Internal-min / hire-max ratios and the shortfall penalty are hardcoded
  defaults**, not sourced from `OptimisationPolicy` yet (OD-08 in the spec
  covers the confidence weights; the mix/roster policy constants here are
  the same kind of gap).

## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Docs at `http://localhost:8000/docs`. Every request needs an
`X-Tempo-Context` header (see `tests/conftest.py::context_header` for the
shape) and run-creation calls need an `Idempotency-Key` header. The four
implemented run types need canonical data seeded first — see
`tests/factories.py::seed_named_roster_scenario` for the minimum dataset
(historical `DemandBucket`, a `WorkStandard`, an `ActivityRoleZoneMap`,
active `Worker`/`SkillCertification`/`LabourCostRule` rows).

## Test it

```bash
pytest
```

`tests/test_solvers.py` checks the actual mathematical properties (hire
ratio never breached, no worker double-booked) rather than just that the
API plumbing works.
