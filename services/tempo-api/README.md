# Tempo Optimisation Service — Phase 0 + Phase A + Phase B (Deputy)

A FastAPI implementation of the contract foundation (Phase 0), the four
core Labour Intelligence models (Phase A), and the Deputy overlay connector
(Phase B) from `Tempo_Prime_AI_Integration_Specification_v2.0.docx` (§18):
Phase 0's exit outcome — *"Prime can call a stubbed Tempo run end-to-end
with governed evidence"* — Phase A's four real solvers, and Phase B's —
*"customers retain T&A while using identical Prime/Tempo capability
contracts."*

**Architecture note on where Phase B lives**: the spec's own architecture
(§3.1 "Prohibited coupling", DP-03/INT-002) requires vendor-specific logic
to live only in Maestro, never in Tempo's solvers. That boundary is
preserved in code — `app/maestro/` has zero imports from `app/solvers/` and
vice versa, and the solvers never branch on `source_system`. What's
**not** yet true to the target architecture: Maestro is supposed to be its
own service with its own datastore, publishing to Tempo over an API/event
boundary (§17.1's "Datastore decision" explicitly rules out shared
tables). This scaffold keeps `app/maestro/` in-process with Tempo, sharing
its database, because standing up a second service was out of scope for
this pass. That's tracked debt, not an accepted design — see "Known
simplifications" below and `docs/roadmap.md`.

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

Phase B — the Deputy connector, in `app/maestro/deputy/` (§2.1, §2.3, §7.1):

| Component | What it does |
|---|---|
| `client.py` | Bearer-token REST client, 500-record pagination, retry-with-backoff-and-jitter on 429/5xx |
| `mapping.py` | Employee/Timesheet/Roster/Leave → canonical envelope (§6.2), with data-quality classification (§6.3) — never silently defaults a required field |
| `connector.py` | Bounded backfill with a resumable checkpoint (`ConnectorCheckpoint`); resolves each record's Deputy employee id to a canonical `worker_id`, quarantining (not dropping) anything that arrives before its dependency |
| `app/core/ingestion.py` | Shared idempotent upsert + dead-letter routing (`IngestionDeadLetter`) — any future connector (UKG) calls this too, not its own copy |

`tests/test_source_parity.py` is the concrete proof this is wired right,
not just architecturally asserted: it runs the identical `workforce_mix`
solver against a Tempo-native tenant and a Deputy-sourced tenant seeded
through the real connector pipeline, and checks the labour cost and
coverage come out identical (Integration Spec AC-02).

**Not implemented in Phase B** — flagged, not silently skipped:
- **Skill/Certification mapping** — §2.3 itself notes Deputy has no native
  cert object ("map via custom fields"); this needs a per-tenant
  custom-field schema this scaffold doesn't have.
- **TimesheetPayReturn** (pay-rule/cost detail) — `AttendanceSession.pay_code`
  is left unset; `LabourCostRule` is still tenant-configured directly.
- **UKG Pro WFM / UKG Ready** — spec's own sequencing says Deputy first;
  next up, same `app/maestro/<vendor>/` shape.
- **Real webhook signature verification** — the connector only does bounded
  backfill; incremental sync is a plain re-run with a watermark, not a
  webhook receiver yet.

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

Phase B:
- **Deputy field names are unverified against a live tenant** — see the
  warning at the top of `app/maestro/deputy/client.py` and `mapping.py`.
  The pagination/auth/retry *behaviour* and the canonical mapping *shape*
  are real and tested; the literal Deputy JSON field names need a sandbox
  check before pointing this at a real customer.
- **Maestro shares Tempo's database and process** rather than being a
  separate service — see the architecture note above.
- **Per-entity watermarks aren't independent** — one backfill call uses a
  single `modified_since` across employees/timesheets/rosters/leave rather
  than each entity type tracking its own delta cursor.

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
