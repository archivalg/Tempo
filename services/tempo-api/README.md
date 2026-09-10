# Tempo Optimisation Service — Phases 0, A, B, C, D, E, F

A FastAPI implementation of the contract foundation (Phase 0), the four
core Labour Intelligence models (Phase A), the overlay connectors (Phase
B — Deputy, UKG Pro WFM, UKG Ready), operational breadth (Phase C —
training/certification, leave/RDO, intraday reallocation, WMS backlog
ingestion), enterprise intelligence (Phase D — team composition, 3PL
cost-to-serve/margin, robust/scenario planning), controlled action
(Phase E — action validation, approval, writeback, reconciliation), and
scale/optimisation groundwork (Phase F — capacity tests, model monitoring,
connector catalogue, self-service onboarding) from
`Tempo_Prime_AI_Integration_Specification_v2.0.docx` (§18): Phase 0's exit
outcome — *"Prime can call a stubbed Tempo run end-to-end with governed
evidence"* — Phase A's four real solvers, Phase B's — *"customers retain
T&A while using identical Prime/Tempo capability contracts"* — Phase C's
three additional models plus their live data feed, Phase D's three
remaining models from the AI Labour Optimisation Spec's full ten-model
catalogue, Phase E's §12 controlled-action pipeline, and Phase F's
operational-maturity layer over everything Phases 0-E built. **Every
model and run_type Appendix C's enum names is implemented, every
recommendation those models produce can be validated, approved and
(honestly) written back, and the service now measures its own solver
performance, model drift, and lets a tenant onboard itself.**

**Architecture note on where Phase B/C connectors live**: the spec's own
architecture (§3.1 "Prohibited coupling", DP-03/INT-002) requires
vendor-specific logic to live only in Maestro, never in Tempo's solvers.
That boundary is preserved in code — `app/maestro/` has zero imports from
`app/solvers/` and vice versa, and the solvers never branch on
`source_system`. What's **not** yet true to the target architecture:
Maestro is supposed to be its own service with its own datastore,
publishing to Tempo over an API/event boundary (§17.1's "Datastore
decision" explicitly rules out shared tables). This scaffold keeps
`app/maestro/` in-process with Tempo, sharing its database, because
standing up a second service was out of scope for this pass. That's
tracked debt, not an accepted design — see "Known simplifications" below
and `docs/roadmap.md`.

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
spec's own pipeline (Strategy doc §4). Phases B, C and D (below) complete
the rest of Appendix C's `run_type` enum; a run_type outside that enum
entirely still returns `TEMPO-RUN-004` rather than a 404 or a stack trace.

Phase B — three connectors in `app/maestro/` (§2.1, §2.2, §2.3, §7.1):

| Component | What it does |
|---|---|
| `deputy/client.py` | Bearer-token REST client, 500-record pagination, retry-with-backoff-and-jitter on 429/5xx |
| `deputy/mapping.py` | Employee/Timesheet/Roster/Leave → canonical envelope (§6.2), with data-quality classification (§6.3) — never silently defaults a required field |
| `deputy/connector.py` | Bounded backfill with a resumable checkpoint (`ConnectorCheckpoint`); resolves each record's Deputy employee id to a canonical `worker_id`, quarantining (not dropping) anything that arrives before its dependency |
| `ukg/pro_wfm_client.py`, `ukg/ready_client.py` | UKG "is not one API" (§2.2) — different auth (OAuth2 tenant key vs. plain API key) and endpoint shapes, but each client normalizes to the identical record shape, so... |
| `ukg/mapping.py`, `ukg/connector.py` | ...there's exactly one UKG mapping module and one UKG connector algorithm, parametrized by which client (product line) was constructed at onboarding — not two near-duplicate connectors |
| `app/core/ingestion.py` | Shared idempotent upsert + dead-letter routing (`IngestionDeadLetter`) — all three connectors call this, none has its own copy |

`tests/test_source_parity.py` is the concrete proof this is wired right,
not just architecturally asserted: it runs the identical `workforce_mix`
solver against a Tempo-native tenant and, in turn, a Deputy-sourced,
UKG-Pro-WFM-sourced, and UKG-Ready-sourced tenant, each seeded through its
real connector pipeline — and all four produce identical labour cost and
coverage (Integration Spec AC-02, DP-04).

**Not implemented in Phase B** — flagged, not silently skipped:
- **Skill/Certification mapping** — §2.3 itself notes neither Deputy nor
  UKG natively covers this ("typically sourced from a separate LMS/
  compliance system" / "map via custom fields" for Deputy specifically);
  needs a per-tenant custom-field/LMS integration this scaffold doesn't have.
- **TimesheetPayReturn / UKG pay codes** (pay-rule/cost detail) —
  `AttendanceSession.pay_code` is left unset either way; `LabourCostRule`
  is still tenant-configured directly.
- **Full UKG Pro HCM** — the spec itself deprioritizes this ("materially
  heavier... only needed for employee master sync, not attendance"); only
  Pro WFM (attendance/scheduling) is implemented.
- **Real webhook signature verification** — every connector only does
  bounded backfill; incremental sync is a plain re-run with a watermark,
  not a webhook receiver yet (Deputy and UKG Pro WFM both support
  webhooks per the spec).

## Phase C (in progress)

First step before adding Phase C's three new models: generalize the
hardcoded policy constants Phase A left behind, so those new models
(leave/RDO approval weights, training-cost thresholds, intraday risk
penalties) don't each reinvent the same gap.

`app/core/policy.py` resolves a tenant's `OptimisationPolicy` — versioned
code defaults, with a stored policy row overriding individual keys (not a
full replacement). `workforce_mix.py`, `named_roster.py`, and
`compute_confidence` all resolve through it now instead of reading module
constants directly. See `tests/test_policy.py` for the override/fallback
behaviour, including the case where a tenant requests another tenant's
`policy_version` (rejected, falls back to their own).

Wiring this up caught a real bug in `named_roster.py`: the fairness-weight
objective term had the same `// 100` double-scaling mistake as the
shortfall-penalty bug found during Phase A — it made the fairness term
~100x weaker than intended, so hour-distribution fairness barely
influenced the roster at all. Fixed alongside the policy wiring (the fix
made named-roster test cases noticeably slower, ~10s vs ~2s, because
fairness now genuinely competes with cost in the search — still well
within the 10s per-solve limit and the spec's 30s target for these run
types, not a regression to chase).

Also wired: `Availability.preference` (defined in the canonical model since
Phase 0, never read by any solver) now feeds Named Roster's objective per
§3.4's `pref_(i,d,k)` term, weighted by policy's `preference_weight`.

**First new model — `training_coverage`** (§3.6 / Appendix A.6, MILP,
`app/solvers/training_coverage.py`): recommends which workers to train or
re-certify to close a projected certification gap. Required coverage comes
from Labour Requirement's hours need (converted to headcount), **not**
from Workforce Mix's assigned headcount — that would be circular, since
`workforce_mix`'s own availability lookup already gates headcount by
current certification, so comparing current supply against a number that
can never exceed current supply can never reveal a shortfall. Caught this
while building `tests/test_training_coverage.py`'s scarcity case (a
fully-staffed scenario correctly showed zero shortfall, but so did an
artificially certification-scarce one — the required-coverage source was
the bug, not the MILP). Cost/benefit/shortage-penalty are flat policy
defaults, the same class of gap as `workforce_mix`'s `default_rate`.

**Second new model — `leave_rdo`** (§3.7 / Appendix A.7, MILP,
`app/solvers/leave_rdo.py`): approves or rejects pending leave/RDO
requests, balancing staffing-gap risk against rejection dissatisfaction.
Same required-coverage fix applies here (sourced from Labour Requirement's
hours, not Workforce Mix's output). A pending request is an `Availability`
row with a new status value (`leave_requested`/`rdo_requested`) alongside
the `available`/`unavailable`/`leave`/`rdo` values Named Roster already
reads; approval priority reuses `Availability.preference`. This model
*decides* approve/reject — it doesn't write the outcome back to
`Availability` (that's Phase E, controlled action/writeback, not a
planning run). `tests/test_leave_rdo.py`'s scarcity case checks the
property that actually matters: when every request can't be granted, it
rejects the lowest-priority ones first, not an arbitrary subset.

**Third new model — `intraday_reallocation`** (§3.5 / Appendix A.5,
**min-cost flow**, `app/solvers/intraday_reallocation.py`): the one
genuinely new solver family in Phase C — a bipartite worker->zone
assignment network solved with OR-Tools' `SimpleMinCostFlow`, not a MILP.
Moves active workers between zones to cover live backlog at minimum
disruption cost; a worker's current zone is always a zero-cost option, so
surplus workers stay put rather than moving pointlessly. Processes a
single current interval (`planning_window.start` for one
`bucket_minutes`), not the whole window — "intraday" means right now, and
a real caller would invoke this again for the next interval.

Added a new canonical table, `ZoneBacklog`, ahead of any real connector the
same way `DemandBucket` existed before any Phase A solver read it.
`tests/test_intraday_reallocation.py` checks the property that matters:
an idle worker in a zone with no backlog gets moved to a zone that's
short, while already-adequately-staffed zones see no movement at all.

**Fourth Phase C item — WMS backlog ingestion** (§7.2's "Active tasks /
backlog" domain, `app/maestro/wms/`): closes the loop `intraday_reallocation`
needed. No specific WMS vendor is named in the spec (unlike Deputy/UKG),
so `client.py` is explicitly illustrative REST (bearer token, generic
`/backlog` resource) rather than matched against a real vendor API — same
disclosed-uncertainty pattern as the Deputy/UKG clients, just with no
vendor at all to eventually verify against; adapt the endpoint/field names
to whichever WMS a real tenant runs. Simpler than Deputy/UKG's connectors
in one respect: a backlog snapshot isn't tied to a worker, so there's no
FK-resolution/quarantine-until-dependency-arrives step.
`tests/test_intraday_wms_integration.py` is the same kind of proof
`test_source_parity.py` is for Deputy/UKG: it runs `intraday_reallocation`
against backlog ingested through the real `WmsConnector` pipeline, not a
direct insert, and gets the same correct reassignment.

**Phase C is now fully done.**

## Phase D — enterprise intelligence

The last three models from the AI Labour Optimisation Spec's ten-model
catalogue (§18's "Team composition, 3PL cost-to-serve/margin, robust/
scenario; restricted finance access").

**`team_composition`** (§3.8 / Appendix A.8, MILP, `app/solvers/team_composition.py`):
picks *which named workers* fill a role/zone team, given how many
workforce_mix already decided are needed there — it doesn't re-decide
headcount or the internal/labour-hire mix, it decides identity, trading
off productivity/cost/quality targets against reliability and minimum
internal/mentor coverage. Per-worker productivity/quality/reliability
ratings and the mentor flag live in a new table, `WorkerPerformanceProfile`
— a Tempo-governed addition (same tier as `ActivityRoleZoneMap`), not a §6.1
canonical entity, since no connector in scope publishes these ratings; a
worker with no row is assumed exactly average, not excluded. Building this
surfaced a real property of the formal spec worth flagging rather than
"fixing": Appendix A.8's deviation terms (`|Σprod·x − ProdTarget| ≤ u_prod`)
are symmetric, so the model can prefer a low-productivity worker who
exactly closes the gap over an average worker whose surplus would only
inflate overshoot — verified deliberately with a manual before/after case
(see the solver module's docstring), not silently patched with an
asymmetric penalty the spec doesn't specify.

**`margin_3pl`** (§3.9 / Appendix A.9, MILP, `app/solvers/margin_3pl.py`):
the customer-profitability counterpart to workforce_mix's pure-cost view —
maximises contribution margin (revenue − labour cost − overtime − overhead
− SLA penalties) instead of minimising cost, deciding how much of each
customer's demand to serve when serving all of it isn't profitable.
Restricted per §5.2: `labour.margin.read` ("Finance, 3PL Commercial") gates
both run creation and `GET /v1/runs/{run_id}` in `app/api/v1/runs.py` — a
caller with `labour.plan` but not `labour.margin.read` is forbidden from
this run_type specifically, even though every other run_type only needs
`labour.plan`. Verified with a deliberately uneconomic customer (high
volume, a sell rate below marginal capacity cost): the model leaves them
partially unserved rather than treating all demand as equally worth
serving (`tests/test_margin_3pl.py`).

**`scenario`** (§3.10 / Appendix A.10, Monte Carlo, `app/solvers/scenario.py`):
stress-tests a workforce_mix plan under demand volatility, absenteeism and
productivity drift, reporting a cost distribution, SLA-breach probability
and labour-risk range instead of a single point estimate.
`request.configuration.objective_profile == "lowest_risk"` selects the
formal spec's robust (worst-case) posture; every other profile uses the
stochastic (expected-value) posture — reusing the existing enum rather than
adding a scenario-specific request field. The biggest scope reduction in
Phase D: the formal model's second stage is itself an optimisation to
re-solve per scenario, which isn't tractable synchronously at the policy
default of 200 scenarios (and this codebase has no async run worker yet —
§18's "heavy scenario runs return async" is Phase D/F scope, tracked in
`docs/roadmap.md`). Recourse per scenario is instead computed analytically
in the same cost order a MILP would pick (overtime, then temp labour up to
a surge cap, then unmet demand at `sla_penalty_per_hour`) — an
approximation, not a re-solved MILP. Scenario draws use a seeded RNG
(policy's `scenario_random_seed`) so a run is reproducible from its inputs
and policy version alone, matching every other run's immutability
requirement rather than being genuinely random each time
(`tests/test_scenario.py` checks this directly, plus that the robust
posture never reports a lower cost than the stochastic one over the exact
same draws).

**Phase D is now fully done — every model in the AI Labour Optimisation
Spec's catalogue and every run_type in Appendix C's enum is implemented.**

## Phase E — controlled action

§12's two-step action contract: a completed run's `Recommendation` (one
per run, created in `app/api/v1/runs.py` right after completion) is a
proposal, never an operational action, until `POST /v1/actions/validate`
then `POST /v1/actions` confirm it — enforced in `app/api/v1/actions.py`,
not just documented. `POST /v1/actions/{action_id}/reconcile` is a
pragmatic addition beyond the two named endpoints (§8.2 only lists
validate/execute), because the spec's own acceptance criteria require
reconciliation to exist somewhere ("A failed/partial source writeback is
reconciled with an auditable outcome").

**Validate** (`app/api/v1/actions.py::validate_action`) checks, in order:
caller has `labour.plan`; the recommendation exists, belongs to the
caller's tenant, and hasn't expired (`recommendation_ttl_seconds`,
policy-tunable); the requested `action_type` matches the recommendation's
`run_type` via a fixed table (`publish_roster` ↔ `named_roster`,
`update_assignment` ↔ `intraday_reallocation`, `approve_leave` ↔
`leave_rdo`, `create_training_plan` ↔ `training_coverage` —
`ACTION_TYPE_RUN_TYPE` in `app/schemas/actions.py`, not named explicitly
in the spec text); the caller's `expected_source_version` matches a new
`SourceVersionWatermark` table's tracked version for that
(tenant, connection, site, resource) — a real optimistic-concurrency
check, not a stub, though nothing populates the watermark except this
service's own confirmed writebacks (there's no live vendor to poll one
from). On success it issues an HMAC-signed, short-lived `action_token`
(`app/core/action_tokens.py` — no JWT dependency, since this service is
its only verifier) and returns an impact summary lifted directly from the
recommendation's own baseline/proposed/delta/confidence — no separate
diff computation needed, since every run already produces exactly that.

**Execute** (`execute_action`) requires `labour.approve` — a distinct,
narrower permission than `labour.plan`, so a Planner can preview an
action's impact but only an Operations Manager can actually approve one,
matching §5.2's role table precisely. It recomputes the payload hash from
the resent request body and the token hash from the resent token, re-checks
source-version drift (the source may have moved between validate and
execute), then hands off to a `WritebackClient`
(`app/maestro/writeback.py`).

**The central honest simplification of Phase E**: there is no real vendor
writeback connector. §18.1 itself says writeback shouldn't be MVP scope
"unless a named pilot requires it and the source offers a reversible
staging state," and there's no live tenant or sandbox credential to build
one against — the same gap WMS's read-side client discloses, just with no
partial credit this time. Rather than fabricate a `confirmed` outcome no
real vendor ever returned, the default `NotImplementedWritebackClient`
always answers `unknown`, which forces every execution down the same
reconciliation path a real, still-processing vendor call would need. This
is a stronger claim than "adapt the endpoint names later" — it's "this
service currently cannot honestly tell you a write succeeded." Tests
substitute a `FakeWritebackClient` (same pattern as Deputy/UKG/WMS's fake
HTTP clients) to exercise the `confirmed`/`rejected` paths.

Every execute/reconcile response is HTTP 202 with the business outcome in
the body (`confirmed`/`rejected`/`partially_confirmed`/`unknown`) — the
same design run completion already uses (`completed` vs
`completed_with_warnings` is a 202 either way). HTTP-level errors
(permission denied, expired token, version drift, type mismatch, not
found) are the only things that raise a `TempoError`; a legitimately
`rejected` writeback is not a request-level failure and must not roll back
the audit trail recording that it happened.

Two error codes extend beyond the Integration Spec's four named
`TEMPO-ACTION-00x` codes (§8.6 only defines 001-004): `TEMPO-ACTION-005`
(recommendation/action not found) and `TEMPO-ACTION-006` (action_type
doesn't match the recommendation) — the same kind of disclosed, pragmatic
extension `ZoneBacklog`/`ActivityRoleZoneMap` are on the canonical model
side, for gaps the spec's own four codes don't cover.

**Phase E is now fully done — every controlled-action guarantee the spec
names (proposal-until-approved, expiring tokens, version-drift detection,
idempotent execution, and reconciliation before retry) is implemented and
tested**, short of the one thing genuinely out of this codebase's reach: a
real vendor to write back to.

## Phase F — scale and optimisation

§18's last phase: "Capacity tests, model monitoring, connector catalogue,
self-service onboarding." Four real, tested pieces, each closing a gap
disclosed since earlier phases rather than adding new solver logic.

**Capacity tests** (`tests/test_capacity.py`) answer §15.1's SLO table
("Simple run completion p95 <= 30 seconds... at agreed pilot scale",
"Intraday recommendation p95 <= 60 seconds") and §16.1's Solver test layer
requirement for "performance" evidence, which nothing before Phase F
checked — every prior solver test used small, hand-built fixtures sized
for clarity, not scale. These seed 150 workers across 21 days (chosen
empirically — see the test module's docstring for why) and assert real
wall-clock time for every solver against the spec's targets: named_roster
(the slowest, CP-SAT with the largest variable count) finishes in
single-digit seconds, an order of magnitude under its 30s budget.

**Model monitoring** (`app/core/monitoring.py`, `GET /v1/monitoring/models`,
`POST /v1/monitoring/models/drift-check`) computes §15.2's "Model
operations" signals (backtest error, drift, solver gap, version adoption)
entirely from `OptimisationRun` history every phase already writes — no
new telemetry pipeline. `check_drift` splits a run_type's runs into an
older and a more recent half and flags drift when the recent half's
average confidence dropped, or average backtest MAPE rose, past a policy
threshold, publishing `model.drift.detected` (§13.1) when it fires. There
is no background scheduler in this codebase (the same gap `scenario` and
`recommendation.expiring` disclose), so drift-check is on-demand, not
continuous — call it after a batch of runs, not expect it to fire itself.

**Connector catalogue** (`app/core/connector_catalogue.py`,
`GET /v1/connectors`) is a read registry describing what `app/maestro/`
actually implements (Deputy, UKG Pro WFM, UKG Ready, WMS — their entity
types, auth shape, and GA-vs-illustrative status) so a tenant admin or
Prime can discover what's available over the API instead of reading
source. It's descriptive, not new integration logic.

**Self-service onboarding** (`app/api/v1/onboarding.py`) closes the
Phase 0-disclosed gap that every `TenantScope` and connector row so far
only ever existed via direct DB insert or a seed script
("Canonical ingestion" in Phase 0's simplifications below).
`POST /v1/tenant-scopes` then `POST /v1/connections` (both `labour.configure`,
Tenant Admin) let a tenant declare its sites and connector instances
through the API — `POST /v1/connections` validates `source_system` against
the catalogue above and requires the target site's `TenantScope` to exist
first, a real (if small) piece of onboarding-order enforcement, not just a
row insert. What it deliberately does **not** do — because no credential
vault exists in this scaffold — is configure a live vendor credential or
trigger ingestion: every registered `MaestroConnection` stays
`pending_credentials` forever in this codebase, honestly, the same class
of gap Phase E's writeback connector discloses.

**Phase F is now fully done — every §18 phase this codebase set out to
build is implemented**, each with its scope reductions disclosed here
rather than hidden, and its remaining gaps (no real vendor writeback or
credential vault, no background scheduler, analytic Monte Carlo recourse)
named as what a production pilot would need to add next, not silently
smoothed over.

## Beyond §18 — serving services/tempo-console

`services/tempo-console` (Business Spec §4/§8's "Real-Time Operations
Console") is this API's first real UI consumer, and it needed two small,
honest additions beyond §18's own roadmap:

- **`GET /v1/runs`** and **`GET /v1/actions`** — cursor-paginated list
  endpoints (§8.1's "cursor-based; stable sort; maximum page size 500"),
  since `GET /v1/runs/{run_id}` and `GET /v1/actions/{action_id}` alone
  can't back a list view. `list_runs` silently excludes `margin_3pl` rows
  for a caller without `labour.margin.read` rather than 403ing the whole
  list — the same restriction `GET /v1/runs/{run_id}` enforces per-row,
  applied per-row here too.
- **`GET /v1/runs/{run_id}`** now also returns `run_type` and
  `recommendation_id` on a completed run (previously only in the
  run-creation response), so the console can offer "start an action from
  this run" without the caller needing to keep the create-run response
  around.

Also added CORS (`app/main.py`, `TEMPO_CONSOLE_CORS_ORIGINS` /
`console_cors_origins` in `app/config.py`, default
`http://localhost:5173`) — a real deployment sets this to the console's
actual origin(s); the default is a local-dev convenience, same class of
stand-in as `action_token_secret`.

## Beyond §18 — native capture (Standalone mode)

Business Spec §4/§5 names Standalone mode's own "Time & Attendance (native
capture path)" — PIN/GPS/NFC clock-in — as a first-class deployment
option, not a fallback behind Overlay. Before this, every canonical row
came from either a direct DB seed or one of the four Overlay connectors;
there was no clock-in API at all, so "Standalone" was really just "not
Overlay." `app/api/v1/attendance.py` and `app/core/attendance.py` close
that gap:

- **`POST /v1/attendance/credentials`** (Tenant Admin, `labour.configure`)
  enrolls a worker's PIN and/or NFC tag — `WorkerCredential`
  (`app/models/attendance.py`), a hash never the plaintext, unique per
  tenant so resolving "who just tapped in" has exactly one answer.
- **`POST /v1/attendance/clock-in`** / **`clock-out`** resolve the worker
  from the presented PIN or NFC tag and write directly to the existing
  `AttendanceSession` canonical table — no Maestro connector involved,
  no RBAC gate beyond tenant/site scope (a kiosk isn't an RBAC principal;
  the credential itself is the authentication, same as a real T&A kiosk).
  One open session per worker at a time; a clock-in that doesn't match any
  rostered `ShiftAssignment` still succeeds but is flagged
  `matched_rostered_shift: false` in the response — a starting point for
  §9's "every exception visible... within 15 minutes," not a full
  exception system.
- **`POST /v1/site-geofences`** (Tenant Admin) configures optional GPS
  bounds per site (`SiteGeofence`); a site with no geofence configured
  skips the check rather than failing closed — PIN/NFC alone is a
  legitimate configuration too.
- **`GET /v1/workers/{worker_id}/shifts`** — the Worker UX role's "know
  shifts" need, scoped by tenant only (no per-worker identity exists yet,
  same Phase 0 stand-in as everything else here).
- **`POST /v1/attendance/whoami`** — resolves a worker from PIN/NFC
  *without* clocking in, for `services/tempo-console`'s Kiosk page to
  greet the worker and show their shifts before they commit to an
  actual clock-in/out.
- **`GET /v1/sites/{site_id}/attendance`** — the Supervisor UX role's
  "cover shifts, manage exceptions" need: every attendance session at a
  site in a configurable window, each annotated with whether it matches
  a rostered shift — computed on read, not stored, same convention as
  the clock-in response's own flag applied to a whole site.

**The other half of this gap, closed at the same time**: publishing a
roster or approving leave previously always hit Phase E's
`NotImplementedWritebackClient`, honestly reporting `unknown` even for a
Tempo-native target — but Standalone mode doesn't need a vendor call to
commit its own data. `app/maestro/native_writeback.py`'s
`TempoNativeWritebackClient` is a second, genuinely *working* writeback
client, selected in `app/api/v1/actions.py`'s `_get_writeback_client` when
`target.system == "tempo_native"`:

- `publish_roster` promotes the `ShiftAssignment` rows `solve_named_roster`
  already writes at `status="proposed"` (every roster run gets a
  canonical record, published or not) to `status="committed"` — it must
  never insert a second row. This was a real bug caught while building it:
  the first version blindly inserted a fresh row per assignment, silently
  doubling every published run's `ShiftAssignment` rows (14 solved + 14
  inserted = 28, one seeded test scenario's exact reproduction — caught by
  comparing row counts before/after publish, not just checking the
  response body).
- `approve_leave` updates the matching `Availability` rows from
  `leave_requested`/`rdo_requested` to `leave`/`rdo`. A recommendation that
  approves nobody (a legitimate outcome under severe staffing shortage)
  reports `confirmed`, not `rejected` — there's nothing wrong with
  correctly applying zero approvals. A partial match (some approved
  decisions found no corresponding row) reports `partially_confirmed` —
  the first real use of that status value anywhere in this codebase.
- `update_assignment` (intraday_reallocation) and `create_training_plan`
  have no defined native write target — what "committing" an intraday
  move or a training plan means for Tempo's own tables isn't specified
  anywhere in the source docs — so both still report `unknown` even for a
  `tempo_native` target, disclosed rather than guessed at.

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
- ~~Internal-min / hire-max ratios and the shortfall penalty are hardcoded
  defaults, not sourced from `OptimisationPolicy` yet~~ — **closed** by
  `app/core/policy.py` (Phase C prep): versioned code defaults
  (`DEFAULT_POLICY_VERSION`) plus an admin-override slot (a tenant's
  `OptimisationPolicy` row, partial-merged over the defaults). Confidence
  weights (OD-08) now come from the same resolver, so a tenant override
  applies to both the solver ratios and the explanation contract's
  confidence score, not just one or the other.

Phase B:
- **Deputy and UKG field names are unverified against a live tenant** — see
  the warnings at the top of each `client.py`/`mapping.py`. The
  pagination/auth/retry *behaviour* and the canonical mapping *shape* are
  real and tested; the literal JSON field names need a sandbox check
  before pointing this at a real customer.
- **UKG employment-category inference is a hardcoded keyword heuristic**
  (`app/maestro/ukg/mapping.py`'s `_CATEGORY_KEYWORDS`) — real UKG
  category taxonomies vary by tenant and should eventually be a per-tenant
  policy mapping, not guessed from substring matches.
- **Maestro shares Tempo's database and process** rather than being a
  separate service — see the architecture note above.
- **Per-entity watermarks aren't independent** — one backfill call uses a
  single `modified_since` across employees/timesheets/rosters/leave (or
  punches/shifts/accruals for UKG) rather than each entity type tracking
  its own delta cursor.

Phase C:
- **No specific WMS vendor is named in the spec**, so `app/maestro/wms/client.py`
  is illustrative REST rather than matched against a real vendor API —
  there's no live tenant to eventually verify it against the way Deputy/UKG
  have one; adapt it entirely when a real WMS is chosen.
- **Training/leave/intraday's cost, benefit, and risk constants** are flat
  policy defaults (`app.core.policy`), the same class of gap as
  `workforce_mix`'s `default_rate` — see each solver's own docstring.
- **Intraday reallocation processes one interval at a time**, not a
  rolling window — a real deployment calls it again for the next interval.
- **Intraday reallocation's productivity/move-cost are flat**, same
  simplification as Workforce Mix's productivity-fixed-at-1.0.

Phase D:
- **`team_composition` sizes one stable named team per (role, zone)** to
  the peak daily headcount workforce_mix assigned across the window, not a
  different roster each day — matching the spec's framing ("the best
  employee mix for a team or shift"), not named_roster's day-by-day
  problem.
- **`WorkerPerformanceProfile` is new, Tempo-governed configuration**, not
  sourced from any connector — no vendor in scope publishes per-worker
  productivity/quality/reliability ratings; a worker with no row is
  assumed exactly average via policy defaults.
- **`margin_3pl` reads customer-split demand directly from `demand_bucket`
  for the planning window**, not forecast — Phase A's `forecast_demand`
  doesn't carry `customer_id` through, and contracted per-customer volumes
  are typically known in advance anyway. It also uses one representative
  `LabourCostRule` per role (preferring `permanent`) rather than
  re-optimising the internal/labour-hire mix — that trade-off stays
  workforce_mix's job. SLA minimum-service floors aren't modelled; only
  the missed-service penalty discourages leaving demand unserved.
- **`scenario`'s recourse is computed analytically per scenario**, not by
  re-solving a MILP per Monte Carlo draw — see the Phase D section above
  for why. Scenario generation parameters (volatility, absenteeism,
  productivity drift) are flat policy defaults, same class of gap as
  `workforce_mix`'s `default_rate`.
- **No async run worker yet** — §18's "heavy scenario runs return async
  with progress state" isn't built; `scenario` runs synchronously like
  every other run type, bounded by the policy default scenario count (200).

Phase E:
- **No real vendor writeback connector exists** — the central, deliberate
  gap; see the Phase E section above. `NotImplementedWritebackClient`
  always reports `unknown`, never a fabricated `confirmed`.
- **`compensated` (approved reversal/compensating action) has no code path**
  — Appendix C's action_status enum includes it, and `ActionRequest.status`
  can hold the string, but nothing transitions an action there; a
  reversal action_type isn't one of the four the spec names
  (`publish_roster`/`update_assignment`/`approve_leave`/
  `create_training_plan`), and building a whole reversal-action pipeline
  wasn't part of this pass.
- **One `Recommendation` per completed run**, not one per alternative —
  `outcome.alternatives` isn't expanded into separately-actionable
  recommendations.
- **`recommendation.expiring` (§13.1) isn't published** — that requires a
  background scheduler to notice an *approaching* expiry, which this
  synchronous, no-async-worker service doesn't have; recommendations still
  expire correctly (checked at validate time), they just don't warn ahead
  of time.
- **`SourceVersionWatermark` only reflects this service's own confirmed
  writebacks** — nothing polls a real vendor for its actual current
  version, since there's no real vendor connector to poll (same root gap
  as above). A tenant's very first action against a given target always
  validates against `expected_source_version: null`.
- **`action_token_secret` has a fixed development default** — same class
  of Phase 0 stand-in as the `X-Tempo-Context` header; a real deployment
  must override it via `TEMPO_ACTION_TOKEN_SECRET`.

Phase F:
- **Capacity tests measure one run, not a statistical p95** — a single
  seeded run at pilot-ish scale finishing well under the spec's target is
  a meaningful regression guard, not a rigorous p95 measurement over many
  concurrent runs, which would need real load-testing infrastructure this
  codebase doesn't have.
- **Drift detection is on-demand, not continuous** — no background
  scheduler exists to run it automatically (same root gap as
  `recommendation.expiring`); call `POST /v1/monitoring/models/drift-check`
  after a batch of runs.
- **`MaestroConnection` records intent, not a live integration** —
  registering one never configures a real vendor credential or triggers a
  backfill; it stays `pending_credentials` forever in this codebase. A
  real deployment still needs an engineer (or a future credential-vault
  feature) to wire up the actual HTTP client before a connection does
  anything beyond exist as a row.
- **The connector catalogue is a static, hand-maintained list** — adding a
  fifth connector means editing `app/core/connector_catalogue.py`, not a
  dynamically-discovered registry.

Native capture:
- **PIN/NFC only, no biometric** — the Business Spec also names biometric
  clock-in; that needs a hardware integration this codebase can't provide.
- **No per-worker identity** — `GET /v1/workers/{worker_id}/shifts` is
  scoped by tenant only; any caller in the tenant's scope can view any
  worker's shifts. A real deployment needs a worker to only ever see
  their own, which needs actual worker-level auth this codebase doesn't
  have (same root gap as everything gated only by `X-Tempo-Context`).
- **A clock-in with no matching rostered shift still succeeds** — flagged
  `matched_rostered_shift: false` in the response, not blocked or
  escalated; there's no exception/alerting system built on top of that
  flag yet.
- **Native writeback covers `publish_roster` and `approve_leave` only** —
  `update_assignment` and `create_training_plan` have no defined native
  write target (see above) and still report `unknown` even for a
  `tempo_native` action.
- **One open `AttendanceSession` per worker** — a second clock-in before
  clocking out is rejected outright, not treated as an implicit clock-out
  of the previous session (a real kiosk usually asks first).

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

`scripts/seed_e2e.py` is a separate dev/test-only utility, not part of
the application or the pytest suite — it seeds a fixed, deterministic
dataset for `services/tempo-console`'s Playwright E2E suite (see that
service's README) and is invoked by that suite's own config, not run
directly in normal development.
