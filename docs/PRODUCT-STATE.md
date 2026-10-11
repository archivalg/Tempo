# Tempo — current product state (11 October 2026)

**This is the entry document.** It answers one question: *what does Tempo actually do today,
and how do you know?* Every claim below is labelled **Deployed**, **Branch-only**, **API-only**,
or **Planned**, and points to the evidence (a test, a file, a screenshot, a live check) rather than
asserting it. Where this document and an older one disagree, **this document wins** for current
status; the older document's own history is kept, not deleted (see each section's links).

- **Deployed revision**: `6723cb0` (code) / `168c7d8` (this doc's own deployment-record commit) on
  branch `build/order-driven-planning`, live at `https://tempo.ensemblesolutions.com.au/`.
  Full detail, migration head, rollback procedure: [`DEPLOYMENT.md`](DEPLOYMENT.md).
- **This branch is not yet merged to `main`.** "Deployed" means *this branch's head is what is
  actually running*, not that the work has passed a merge/release gate. Treat "Deployed" and
  "on `main`" as two different questions throughout this document.
- **Delivery plan and milestone authority**: [`roadmap.md`](roadmap.md) (per `AGENTS.md`). This
  document is a snapshot of *current capability*, not a replacement for the roadmap's phase plan.
- **Historical build ledger**: [`build-progress.md`](build-progress.md) — kept for history; stale
  statements there are marked `[superseded]` rather than deleted, the same convention this document
  follows.

---

## 1. Product overview

**Purpose.** Tempo answers one operational question for a warehouse or 3PL site: *who should work,
where, when, at what cost, and what actually happened against the plan?* It plans labour two ways —
from statistical demand forecasts (the original ten-model catalogue) and, as of this branch, directly
from known customer orders with real deadlines, process steps and dependencies — and it captures
actual attendance natively (kiosk PIN/NFC) or through an external workforce system.

**Intended customers.** Warehouse operators and third-party logistics (3PL) providers who need to plan
and cost labour against either a demand forecast or firm order commitments, and who want attendance,
rostering and reporting in one system — standalone, or as an overlay on an existing Deputy/UKG
deployment.

**Modules** (detail in §7 and the capability register, §2):
- **Planning** — ten forecast-driven optimisation models (demand forecast, labour requirement,
  workforce mix, named roster, training coverage, leave/RDO, intraday reallocation, team composition,
  3PL margin, scenario) plus the order-driven scheduler (`order_fulfillment`) added this branch.
- **Data ingestion** — CSV import (deployed, mature) and XLSX workbook import (deployed this branch,
  Console, fixture-tested — see §4).
- **Rostering** — versioned roster drafts, validation, approval, publication, reconciliation.
- **Time & attendance** — native kiosk PIN/NFC capture, corrections, timesheets, variance reporting.
- **External connections** — Deputy, UKG Pro WFM, UKG Ready, and a generic WMS ingestion path.
- **Mobile/self-service** — an employee web companion (`/my`) and a mobile API surface; no native
  mobile app binary exists in this repository.
- **Platform/admin** — tenant onboarding, billing (manual subscriptions, no payment processor),
  platform operator console, support sessions, audit.

**Supported workflows today** (see §2 for exact deployment/verification status of each):
upload master data → configure shifts/calendars/rates/rules → forecast demand OR import known orders
→ generate a plan → (forecast path) approve and publish a roster, or (order-driven path) create a run
and review its result → capture attendance → report variance → reconcile.

---

## 2. Capability register

Status key: **Deployed** (running at the URL above) · **Branch-only** (committed on
`build/order-driven-planning`, not deployed — N/A here, everything on this branch IS deployed as of
`6723cb0`; this status would apply to future uncommitted/unreleased work) · **API-only** (reachable
over HTTP, no console UI) · **Console** (has a console page) · **Planned** (not built).

### 2.1 Core forecast-driven planning (pre-existing, all Deployed, all Console)

| Run type | Model | Console | Evidence |
|---|---|---|---|
| `demand_forecast` | Holt linear trend | `/runs/new`, `/demand` | `tests/test_solvers.py` |
| `labour_requirement` | Deterministic hours translation | `/runs/new` | `tests/test_solvers.py` |
| `workforce_mix` | MILP (OR-Tools CBC) | `/runs/new` | `tests/test_solvers.py` |
| `named_roster` | CP-SAT | `/runs/new`, `/roster` | `tests/test_solvers.py`, `tests/test_roster_workflow.py` |
| `training_coverage` | MILP | `/runs/new` | `tests/test_training_coverage.py` |
| `leave_rdo` | MILP | `/runs/new` | `tests/test_leave_rdo.py` |
| `intraday_reallocation` | Min-cost flow | `/runs/new` | `tests/test_intraday_reallocation.py` |
| `team_composition` | MILP | `/runs/new` | `tests/test_team_composition.py` |
| `margin_3pl` | MILP, finance-restricted (`labour.margin.read`) | `/runs/new` | `tests/test_margin_3pl.py` |
| `scenario` | Monte Carlo | `/runs/new` | `tests/test_scenario.py` |

These ten do **not** share a worker pool with `order_fulfillment` (below) — see §5's scheduler
limitations. Running both for overlapping windows at one site is not validated against
double-counting.

### 2.2 Order-driven planning — Arch's 17 requirements

Full detail, exact test names and caveats: [`order-driven-planning.md`](order-driven-planning.md)
(the acceptance ledger near its top). All 17 are **Accepted** as of the sixth pass, each with the
specific residual limitation named below — none are silently claimed complete.

| # | Requirement | Status | Residual limitation |
|---|---|---|---|
| 1 | Order-driven demand, open backlog, no double-counting | **Accepted** | No automatic actuals correlation (§6) |
| 2 | Personal activity rates, precedence, compatible units | **Accepted** | — |
| 3 | Fixed indirect coverage, break relief, no simultaneous direct work | **Accepted** | — |
| 4 | Configurable shifts, overnight, breaks, operating calendars | **Accepted** | Revalidated at scheduling time |
| 5 | Personal weekday start/finish windows | **Accepted** | Overnight-boundary bug found and fixed this branch |
| 6 | Recurring weekly availability + dated leave/RDO + approval workflow | **Accepted** | — |
| 7 | Absenteeism scoped by activity/weekday/shift, no duplicate allowance | **Accepted** | — |
| 8 | Activity/employment-type fill priorities incl. permanent-before-casual | **Accepted** | `customer` scope explicitly rejected, not silently inert |
| 9 | Concurrent min/max headcount | **Accepted** | — |
| 10 | Shared equipment across overlapping activities/shifts | **Accepted** | — |
| 11 | Order-scoped dependencies/lag, next-valid-interval start | **Accepted** | Cross-day accounting is an approximation |
| 12 | Congestion/off-task losses with integration tests | **Accepted** | — |
| 13 | Staging capacity influencing scheduling/rescheduling | **Accepted** | — |
| 14 | Validated unit conversions, no double counting | **Accepted** | — |
| 15 | Effective weekday activity rates changing capacity | **Accepted** | — |
| 16 | Function/area/inbound-outbound mappings preserved | **Accepted** | — |
| 17 | Importable position grades + explicit award rules, used in eligibility AND costing | **Accepted** | — |

**How this is reached**: `POST /v1/optimisations/order_fulfillment`, **Console** via `/runs/new` →
run type `order_fulfillment` (draft only — see §6 for why a committed run needs the API).

### 2.3 Data imports

| Capability | Status | Evidence |
|---|---|---|
| CSV upload, 32 master/forecast/transaction/bulk entities, `CONTRACT_VERSION` 1.8 | **Deployed, Console** (`/data`) | [`data-contracts.md`](data-contracts.md) (regenerated 11 Oct 2026 from the live contract definitions) |
| XLSX workbook upload (multi-sheet, v1/v2 field adapters, atomic apply) | **Deployed, Console** | `tests/test_xlsx_import.py`; `e2e/order-fulfillment.spec.ts` drives the console upload UI end to end |
| **Actual Arch v1/v2 workbook compatibility** | **Unverified** | See §4 — this is fixture-tested import support, not confirmed compatibility with the real files, which have not been supplied to this programme |

### 2.4 Plan lifecycle (committed vs. actual)

| Capability | Status | Evidence |
|---|---|---|
| Draft (non-committed) run | **Deployed, Console** | Default `input.committed` |
| Committed run (`input.committed: true`) | **Deployed, Console** | "Commit this plan" checkbox (New Run) and action (run detail) |
| Release/cancel a commitment | **Deployed, Console** | "Release this commitment" button, run detail — `POST /v1/runs/{run_id}/release-commitment` |
| Explicit actual-completion confirmation | **Deployed, Console** | Per-order lifecycle panel, run detail — `POST /v1/orders/{order_id}/complete` |
| Outstanding vs. available-for-planning quantities | **Deployed, Console** | Per-order lifecycle panel, run detail — `GET /v1/orders/{order_id}` |
| Shared worker commitments (order-driven ↔ roster publish) | **Deployed** | New `WorkerCommitment` ledger; `tests/test_shared_resource_conflicts.py` |
| Automatic actuals-import correlation | **Planned** | Not built; explicit completion is the only supported path today |

### 2.5 Other modules (see §7 for detail; none assumed complete)

| Module | Status |
|---|---|
| Rostering (draft → approve → publish → reconcile) | **Deployed, Console** |
| Time & attendance (native kiosk) | **Deployed, Console** (`/attendance`, `/kiosk`) |
| Deputy / UKG Pro WFM / UKG Ready / WMS connectors | **Deployed, API-only** — real HTTP clients, not certified against a live vendor sandbox (roadmap M4/M5 still open) |
| Mobile (employee web companion `/my`, manager controls) | **Deployed, Console** — no native app binary in this repo |
| Billing | **Deployed, Console** — manual subscriptions; no payment processor connected |
| Platform admin / support sessions | **Deployed, Console** |
| Onboarding / setup wizard | **Deployed, Console** |
| Help library | **Deployed, Console** |

---

## 3. Customer setup

All master data is loaded via CSV or XLSX (§4) through `/data` (Console) or the API, in this
dependency order (the XLSX importer's `app/imports/xlsx.py::_PROCESSING_ORDER` encodes this
explicitly; CSV entities have no enforced order but share the same prerequisites):

1. **Sites** — `site_id`, name, IANA timezone (`Australia/Melbourne`, etc.), operating mode
   (standalone/overlay). A site's timezone cannot be changed by re-upload.
2. **Customers** — your own customer records, for scoping orders/process templates.
3. **Zones** — named areas within a site (pick, pack, stage); used by activity roles, process steps,
   staging capacity.
4. **Work standards** — seconds-per-unit per activity (the v1 field name; v2 workbooks instead supply
   `standard_rate_per_hour`, converted automatically — see §4). Optional `function`/`flow` grouping and
   `required_skill` (a qualification gate, distinct from an award restriction — item 17 above).
5. **Workers** — your own worker ref, name, site, employment type, skills (v1 column `skill_code`, v2
   `role` — both map to the same field), optional `position_grade` and `award`.
6. **Availability** — dated leave/unavailable/RDO entries, and/or **weekly availability patterns**
   (recurring per-weekday earliest-start/latest-finish windows, including overnight).
7. **Rates** — employment-type/role hourly rates, overtime multiplier, agency surcharge; **worker
   activity rates** (a named worker's own rate for one activity, highest precedence); **day rates**
   (an activity's rate for one weekday, between the activity standard and a personal rate); **grade
   rates** (position-grade-differentiated); **award rules** (ordinary hours/day and overtime
   multiplier — an award name alone does nothing without a matching row) and **award eligibility
   restrictions** (an explicit, imported statement that an award may not perform an activity — never
   inferred from the award's name).
8. **Shifts** — operating calendar (open/closed/24h per weekday), shift templates (v1 sheet name
   "Shift Patterns", v2 "Shift Templates"), shift breaks (paid/unpaid, v2 only as a separate sheet —
   see §4's stated limitation on v1's inline breaks).
9. **Equipment** — named pools with a quantity, shared across any activity/shift that references them
   in the same scheduling interval.
10. **Processes** — process templates (a named sequence per site/customer) and process steps (ordered
    activities with lag minutes, optional equipment/zone references).
11. **Constraints** — fill priorities (activity and employment-type scope; `customer` scope is
    explicitly rejected at import, not silently ignored), absenteeism rules (scoped by
    activity/weekday/shift), headcount limits (min/max concurrent), indirect headcount requirements
    (fixed coverage by role/weekday/time window), unit conversions (explicit factors only — a missing
    conversion path is rejected, never guessed), productivity loss (congestion/off-task), staging
    capacity and movements.
12. **Orders** — the known-orders workload itself: order ID, received/despatch-due times, units
    (authoritative) or lines (converted via the unit conversions above), process code.

Every field above that is accepted as "supported" actually changes a calculation somewhere in the
scheduler — see §5 and the acceptance ledger in §2.2 for the specific test proving each one.

---

## 4. Data imports

### 4.1 CSV (mature, Deployed, Console)

32 entities across four data classes (master/forecast/transactions/bulk), `CONTRACT_VERSION` 1.8.
Full field-by-field reference, regenerated directly from the live validator definitions (so it cannot
drift from the code): [`data-contracts.md`](data-contracts.md). Every upload goes through
inspect → stage (validate/preview, nothing applied yet) → apply (explicit, separate action) → optional
undo. Duplicate content or a repeated `Idempotency-Key` is never re-applied. Rejected rows are
reported with reasons and downloadable. Case-insensitive matching (both `unit` and activity names)
and structural (never content-based) blank-row/header skipping were verified this branch after a
content-based "ignore the template's example row" feature was built, found to risk discarding real
customer data, and deliberately reverted — see `order-driven-planning.md`'s "third pass" for the full
account of that decision.

### 4.2 XLSX workbook (Deployed this branch, Console, fixture-tested)

`POST /v1/imports/xlsx/inspect` (read-only preview) and `POST /v1/imports/xlsx/stage` (atomic
stage-and-apply across every recognised sheet, in dependency order, in one transaction — any sheet's
failure rolls back the whole workbook, proven by `tests/test_xlsx_import.py::
test_no_partial_import_left_behind_when_a_later_sheet_fails`). Built from a source-workbook review
that stated:

- Ordinary data sheets: header row 1, metadata rows 2–3, example row 4, data from row 5.
- Rules/reference sheets (Day Rates, Award Rules, Fill Priorities, Headcount Limits, Unit Conversions,
  Grade Rates, Award Eligibility Restrictions) need **sheet-specific** layouts this programme has not
  been given exact row numbers for — an earlier uniform guess for this group was wrong and has been
  **removed**; every one of these sheets currently falls back to the one layout actually confirmed
  (the ordinary data-sheet layout above), a stated, acknowledged guess, not a verified answer.
- v1 uses `seconds_per_unit`, `skill_code`, and a "Shift Patterns" sheet; v2 uses
  `standard_rate_per_hour` (converted: `seconds_per_unit = 3600 / rate`), `role`, and "Shift
  Templates"/"Shift Breaks" sheets. Both are recognised and tested.
- v1's "Shift Patterns" sheet is recognised for its shift-template-shaped columns only; if it embeds
  break definitions inline, those are **not extracted** (the column layout for that was not stated).

**Actual Arch v1/v2 workbook compatibility remains explicitly unverified.** Every number and name
above is fixture-tested — verified against LOCAL files this programme built to match the review's
stated facts — not run against the real supplied files, which have not been provided to this
programme at any point. The exact places to check first once they are: `_DATA_SHEET_LAYOUT`/
`_SHEET_SPECIFIC_LAYOUT` (row positions), `_SHEET_ALIASES` (sheet tab names), `_FIELD_ALIASES`/
`_adapt_work_standards` (v1/v2 column names and conversions) — all in
`services/tempo-api/app/imports/xlsx.py`. Full narrative: `order-driven-planning.md`'s "Sixth pass".

Console UI: `XlsxUploadWizard`, on Data → Load data, alongside the existing per-contract CSV wizard —
file picker → per-sheet inspect preview (recognised/unrecognised, rows, missing required columns) →
one "Load N sheets" action. Verified through a real authenticated browser session driving that UI
(`services/tempo-console/e2e/order-fulfillment.spec.ts`), not a direct `page.request` call.

---

## 5. Planning

**Demand modes** (`order_fulfillment` only): `known_orders` (default — plan from uploaded orders only),
`forecast_only` (plan from `DemandBucket` forecast rows, no orders), `hybrid` (both, sharing one
worker/equipment pool; `forecast_basis` says whether the forecast is the *total* expected demand,
known orders subtracted to avoid double-counting, or *additional* demand on top of them).

**Scheduling model**: `solve_order_fulfillment` (`app/solvers/order_workload.py`) is a deliberate,
documented **greedy, non-MILP, interval-granularity allocator** — not globally optimal, but a real
shared-resource scheduler: workers and equipment are finite, consumed exactly once per
`SCHEDULING_INTERVAL_MINUTES = 60` sub-interval, never double-booked. In one coherent plan: calendars,
shifts, breaks, dated and recurring-weekly availability, personal/day/grade rates, indirect coverage,
fill priorities, absenteeism, equipment pools, headcount limits, congestion/off-task loss, staging
capacity (which can delay a step's completion, not just report it afterwards), and award-aware costing
all influence the same allocation.

**Capacity calculation**: `resolve_activity_rate`'s precedence is personal activity rate → personal
role rate → effective weekday (day) rate → activity standard (optionally productivity-adjusted).
Congestion and absenteeism multiply the effective rate down for an interval; off-task hours are
prorated per sub-interval so splitting a shift into finer intervals never double-deducts a flat
per-shift loss.

**Dependencies**: a process's steps release in sequence (finish-to-start plus `lag_minutes`), scoped
to that order only. A predecessor finishing mid-shift lets its successor start at the next 60-minute
scheduling interval, not the next shift (`SCHEDULING_INTERVAL_MINUTES`) — this specifically closes the
brief's "downstream work must not wait for another shift" requirement.

**Indirect coverage**: reserves a worker for a whole shift instance (not a rotating sub-interval); a
reserved worker is excluded from direct-work eligibility for that entire instance (no double-booking,
proven directly via `result.worker_assignments` interval comparison, not just aggregate hours).

**Staging**: live occupancy tracked from imported movements plus what the scheduler itself produces;
a zone at capacity holds back the step that would overflow it rather than letting it overflow or
silently failing.

**Costing**: grade/provider/effective-dated `LabourCostRule` rows resolve the cost rate; an award's
`ordinary_hours_per_day`/`overtime_multiplier` (only when an explicit `AwardRule` row exists for it)
applies overtime beyond the ordinary threshold, tracked per worker per local calendar day.

**Shortfall reporting**: every order/demand line reports `on_time`, `shortfall_quantity`, and per-step
`shortfall_reason` — one of `missing_skill`, `no_equipment`, `headcount_cap`, `deadline_breach` (the
coarser four-code set named as a known gap in `order-driven-planning.md`). A run's own `feasibility`
is `feasible`, `feasible_with_slack` (something was constrained, named why), or the request is
rejected outright with `InsufficientData`/`SolverInfeasible` and a reason when nothing at all could be
scheduled — never a silent, misleadingly-"complete" result.

**Scheduler limitations, stated plainly**:
- Not a MILP — a greedy allocator can produce a worse plan than a globally optimal one would.
- The ten forecast-driven run types and `order_fulfillment` do **not** share one scheduling pass or
  worker pool for demand purposes; running both for overlapping windows at one site can still double-
  or under-count *demand*. What they now DO share is **resource reservation**: a committed
  `order_fulfillment` run and a published roster both check the new `WorkerCommitment` ledger (and
  `ShiftAssignment.status="committed"`), so neither can double-book a worker's actual time once the
  other has committed/published — see §6.
- Cross-day accounting for a step spanning a day boundary is an approximation.
- `customer`-scoped fill priority is rejected at import, not implemented.
- Automatic actuals correlation is not built (§6).

---

## 6. Plan lifecycle

Three distinct, deliberately separate concepts — conflating any two of them was a real defect found
and fixed on this branch (`order-driven-planning.md`'s "Fifth pass"):

1. **Scheduled** — any run, draft or committed, that completed. A *preview* of what capacity could do.
2. **Committed** — `input.committed: true` on the run request. Advances `Order.committed_units`, a
   **planned allocation** that stops a *later* run from re-scheduling the same labour, AND reserves
   the workers it allocated (`WorkerCommitment`) against a published roster for the same site.
   Nothing about the physical world is asserted. **Console**: a "commit this plan" checkbox on New
   Run (`order_fulfillment` only), and a "Commit this plan" action on a completed draft run's detail
   page (`/runs/{id}`), which resubmits the same request with `committed: true`.
3. **Actually fulfilled** — `Order.fulfilled_units`, advanced **only** by an explicit
   `POST /v1/orders/{order_id}/complete` call. The solver never writes it. **Console**: a per-order
   lifecycle panel on the run detail page showing outstanding/committed/available/fulfilled quantities,
   with a quantity input and "Confirm completion" action.

A later run's remaining backlog is `units − max(committed_units, fulfilled_units)` — whichever is
larger already means "don't reschedule this", for its own reason. `GET /v1/orders/{order_id}` exposes
both `outstanding_quantity` (`units − fulfilled_units`, the real-world remaining work) and
`available_for_planning` (`units − max(...)`, what's safe to schedule without double-booking) by name,
specifically because they diverge whenever something is committed but not yet confirmed done.

**Cancellation/replacement**: `POST /v1/runs/{run_id}/release-commitment` releases exactly what that
run committed (tracked per-run via the `OrderCommitment` ledger) AND the `WorkerCommitment` rows it
holds, making the work and the worker time available to a new commitment again — a previously-blocked
overlapping commitment (order-driven or a roster publish) is allowed once released; actual completion
(`fulfilled_units`) is never touched by a release. Idempotent. **Console**: a "Release this commitment"
action on a committed run's detail page, reporting exactly how many order allocations and worker
reservations were released.

**Repeated commit requests**: the existing `Idempotency-Key` mechanism (unchanged, pre-existing)
prevents a retried identical request from committing twice; verified for `order_fulfillment`
specifically in `tests/test_committed_vs_fulfilled.py`.

**Console workflows, now complete**: the console has dedicated UI to (a) mark a plan committed
instead of draft, (b) release a commitment, (c) confirm actual completion, and (d) see the
outstanding/committed/available-for-planning/fulfilled split per order — see
`docs/order-driven-planning.md`'s "Shared-resource conflicts and remaining browser workflows" section
for the full detail and `e2e/order-fulfillment.spec.ts` for the browser-session verification of all
four. Workbook (.xlsx) upload (inspect → preview → atomic apply) also has dedicated console UI on
Data → Load data, alongside the existing per-contract CSV wizard.

**Automatic actuals correlation** (matching imported `WorkloadEvent` actuals back to an order
automatically, instead of the explicit endpoint) is **Planned**, not built — explicit completion is
the only supported path today, and is itself fully verified (unit tests + a live production check).

---

## 7. Other product modules

Recorded by actual status, not assumed complete.

- **Connections** (Deputy, UKG Pro WFM, UKG Ready, generic WMS) — real `httpx`-based HTTP clients with
  resumable checkpoints, idempotent upsert and dead-lettering (`app/maestro/{deputy,ukg,wms}/`), not
  canned/stub data. **Not yet certified against a live vendor sandbox** (roadmap M4/M5): real webhook
  signature verification and true watermark-delta polling are stated gaps in each connector's own
  docstring; the second vendor (beyond Deputy) is still an open choice.
- **Onboarding** — self-service setup wizard (`/setup`), connector catalogue. **Deployed, Console.**
- **Roster management** — versioned drafts (`roster_version`/`roster_event`), server-side validation
  (overlap, rest hours, availability, certification, site eligibility), submit/approve/publish/
  reconcile, overlapping-period safety. **Deployed, Console** (`/roster`, `/approvals`).
- **Time & attendance** — native PIN/NFC kiosk capture, optional geofencing, exception lifecycle,
  supervised corrections (the original punch is never overwritten), payroll CSV export. **Deployed,
  Console** (`/attendance`, `/kiosk` — a separate device surface, no session/nav by design).
- **Kiosk** — device enrolment and lifecycle (`devices.py`), PIN/NFC clock-in/out/break
  (`attendance.py`). **Deployed, Console** (`/kiosk`).
- **Mobile** — an employee web companion (`/my`: roster, offers, leave, clockings — explicitly "the
  same information, no push notifications, no installation") plus a manager-side mobile API
  (`mobile_manage.py`: invites, shift offers, leave, messaging). **No native mobile app binary exists
  in this repository.** **Deployed, Console** for the web companion; the mobile API itself is
  consumed by whatever native client exists outside this repo, unverified here.
- **Billing** — plan/subscription records, manual admin (`platform_billing.py`), customer's own
  plan/allowance view (`billing.py`). **No payment processor is connected** — this is administrative
  record-keeping, not real billing collection.
- **Administration** — platform operator console (`/platform`: tenant lifecycle, platform admins,
  support grants), tenant user admin (invite-only), service-client credential issuance for API
  ingestion, audit trail (`/audit`). **Deployed, Console.**
- **Help** — a help library (`/help`). **Deployed, Console.**

---

## 8. Technical architecture

**Services**: `services/tempo-api` (Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16) and
`services/tempo-console` (React 19/TypeScript, Vite).

**API routers** (`app/api/v1/router.py`; prefix `/v1`): auth, devices, platform, operations, rosters,
timeclock, reports, demand, notifications, handoffs, imports, service_clients, users, readiness, runs,
**orders** (new this branch — explicit completion), actions, onboarding, monitoring, attendance,
planning_rules, platform_billing, mobile, mobile_manage, workers, public_docs, support, billing,
availability, providers, ingestion.

**Database** (PostgreSQL 16, row-level security per tenant and per-site-scope): tables grouped by
owning model file include `tenant`/`tempo_user`/membership+grant tables (identity.py), `worker`/
`skill_certification`/`availability`/`work_standard`/`labour_cost_rule` (canonical.py), `order_`/
`process_template`/`process_step`/`order_commitment` (new)/`day_rate` (orders.py), `fill_priority`/
`absenteeism_rule`/`equipment`/`headcount_limit`/`award_rule`/`award_eligibility_restriction`
(constraints.py), `operating_calendar_day`/`shift_template`/`shift_break` (scheduling.py),
`weekly_availability_pattern` (availability_pattern.py), `productivity_loss`/`staging_capacity`/
`staging_movement` (stage4.py), `indirect_headcount_requirement` (indirect.py), `optimisation_run`/
`recommendation`/`action_request`/`audit_record` (runs.py), `roster_version`/`roster_event`/
`demand_override` (rosters.py), `attendance_punch`/`attendance_policy` (attendance.py), `site`/
`customer`/`zone`/`exception_case` (directory.py), `plan_definition`/`tenant_subscription`/
`smtp_config` (billing.py), `worker_user_link`/`shift_offer`/`leave_request`/`push_device` (mobile.py),
`maestro_connection`/`connector_checkpoint`/`ingestion_dead_letter` (connectors.py),
`import_batch`/`import_row`/`import_mapping` (imports.py), `worker_commitment` (new, cross-run-type
worker reservation ledger — orders.py). Eleven Alembic migrations added this branch, `f1a2b3c4d5e6` →
`e9f0a1b2c3d4`, all additive (verified: every `drop_*` call lives only in each migration's own
`downgrade()`).

**Configuration** (`app/config.py`, `Settings(BaseSettings)`, env prefix `TEMPO_`) — names only, no
values: `env` (local/test/uat/production), `database_url`/`database_migration_url` (non-owner/owner DB
roles), `session_signing_key`, `access_token_ttl_seconds`/`refresh_token_ttl_seconds`,
`session_cookie_secure`, `cookie_domain`, `oidc_issuer`/`oidc_audience`/`oidc_jwks_url`,
`dev_idp_enabled` (local/test only — never on a public hostname), `password_auth_enabled`,
`require_https`, `login_max_failures`/`login_ip_limit`/`login_lock_minutes`, `invite_ttl_hours`,
`push_provider` (disabled/mock/expo), `public_app_url`, `expo_access_token`, `sms_provider`,
`jobs_enabled`/`jobs_interval_seconds`, `kiosk_qr_ttl_seconds`, `db_pool_*` (DAT-04),
`db_statement_timeout_ms` (stored, not yet applied), `service_name`, `api_base_path`,
`confidence_method`, `action_token_secret`, `console_cors_origins`. Database connectivity is entirely
via the two `*_database_url` settings (psycopg URLs) — no separate `POSTGRES_*` settings are read by
the application itself (only by the `docker-compose.yml` Postgres container definition).

**Deployment topology** (`docker-compose.yml`): `tempo_postgres` (postgres:16, `127.0.0.1:5439`,
volume `tempo_tempo_pgdata`), `tempo_migrate` (one-shot, owner role, `alembic upgrade head`),
`tempo_backend` (`tempo-api:local`, host port 8007→8000, non-owner `tempo_app` role),
`tempo_frontend` (host port 3007→80), fronted by a separate gateway repo (`central_nginx`) doing
TLS/routing. Full detail: [`DEPLOYMENT.md`](DEPLOYMENT.md).

**CLI** (`python -m app.cli <command>`, `app/cli.py`): `bootstrap-platform-admin`,
`bootstrap-ensemble-demo`/`reset-ensemble-demo` (synthetic demo tenant, non-production),
`set-password`, `reset-mfa`, `unlock-user`, `create-user`, `set-smtp`, `email-platform-invite`,
`run-notification-jobs`, `demo-status`.

**Frontend routes** (`services/tempo-console/src/App.tsx`): public — `/landing`, `/landing2`,
`/kiosk` (device surface, no session/nav), `/invite`; employee self-service — `/my/*`; platform —
`/platform/*`; manager shell — `/`, `/demand`, `/roster`, `/attendance`, `/reports`, `/approvals`,
`/live`, `/runs`, `/runs/new`, `/runs/compare`, `/runs/:runId`, `/actions`, `/actions/new`,
`/actions/:actionId`, `/onboarding`, `/providers`, `/admin`, `/billing`, `/audit`, `/data`, `/setup`,
`/offers`, `/requests`, `/help`, `/help/:id`, `/account`.

---

## 9. Operations

**Install/deploy**: see [`DEPLOYMENT.md`](DEPLOYMENT.md#how-to-deploy-no-data-loss) for the exact,
guarded command sequence (`docker compose build`, `up -d tempo_migrate tempo_backend tempo_frontend`,
check migration logs, run the smoke test). Never `docker compose down --volumes`; never point the demo
reset or browser tests at database `tempo` (the live one — `tempo_test`/`tempo_e2e` are the only
databases the demo reset and Playwright are allowed to touch).

**Backups**: manual `pg_dump -Fc` before every deploy, stored at `~/tempo-backups/` (mode 600),
verified readable (`pg_restore --list`) before trusting it. No automated/scheduled backup exists yet
(a known operational gap).

**Rollback**: tag the currently-running images `*:rollback-<timestamp>` before deploying; to roll
back, retag them `:local`/`:latest` and `docker compose up -d tempo_backend tempo_frontend`. Every
migration on this branch is additive, so older code can run against the new schema unchanged — no
`alembic downgrade` is required for a code-only rollback.

**Health checks**: `/healthz` (process up), `/readyz` (database connected) — both checked by
`scripts/smoke.sh`. Container health: `docker ps` (`tempo_backend` has a Docker healthcheck;
`tempo_postgres` has `pg_isready`).

**Logs**: `docker logs tempo_backend` / `tempo_frontend` / `tempo_migrate` / `tempo_postgres`.

**Troubleshooting/recovery**: a stuck or deadlocked database connection (seen once during this
branch's own test runs, from a duplicated background test process, not a product defect) is resolved
by identifying and terminating the offending backend (`pg_stat_activity`, `pg_terminate_backend`) —
never by deleting the data volume. A failed migration should be investigated from `docker logs
tempo_migrate`; the one-shot job's `restart: "no"` means it will not silently retry.

---

## 10. Verification and roadmap

**Latest deployed revision**: `6723cb0` (`168c7d8` for this doc's own deployment-record commit), live
at `https://tempo.ensemblesolutions.com.au/`, migration head `d8e9f0a1b2c3`.

**Backend test suite**: 524 passed (`pytest -q`, real PostgreSQL, non-owner `tempo_app` role,
`tests/test_capacity.py` included — it was investigated and found to have no exclusion mechanism;
it is simply part of the normal suite).

**Browser evidence**: `services/tempo-console/e2e/order-fulfillment.spec.ts` drives every order-driven
workflow through a real signed-in browser session against the console UI itself (not raw
`page.request` calls): upload→validate→run→results (happy path); a deliberately constrained run
showing an explained `feasible_with_slack` shortfall rather than a silent success; workbook (.xlsx)
upload through the console's own upload wizard; draft → commit → partial completion → release
(completion untouched by the release) → full completion, all through the run-detail page's UI; and a
repeated completion confirmation past an order's own quantity, shown as reported truthfully rather
than double-counted. Screenshots: `docs/screenshots/order-fulfillment-*.png`,
`docs/screenshots/xlsx-upload-result.png`, `docs/screenshots/order-partial-completion.png`,
`docs/screenshots/order-full-completion.png`.

**Known gaps, prioritised**:

1. **Actual Arch v1/v2 workbook compatibility is unverified** — the single largest open item against
   the supplied brief. The exact files (Tempo v1/v2 templates, Bluegum samples) have not been supplied
   to this programme; Google Drive is not reachable from here, and no file matching those names exists
   anywhere in this repository or host. Only a programme-authored fixture built to the documented v1
   layout has been exercised. Needed: the real files, by exact name.
2. **`order_fulfillment` and the ten forecast-driven run types do not share a worker pool for demand
   purposes** — running both for overlapping windows at one site can still double-/under-count
   *demand* (though resource double-booking is now prevented — see §2.4's new shared-commitment row).
3. **No automatic actuals-import correlation** — explicit completion is the only supported path to
   `fulfilled_units`.
4. External connectors (Deputy/UKG/WMS) are real but uncertified against a live vendor sandbox; the
   second connection (beyond Deputy) is still an open vendor choice (roadmap M4/M5).
5. No automated/scheduled database backup; no secret vault; database connection is not TLS; single
   host, no failover (all pre-existing, unchanged by this branch).
6. Shortfall reason codes remain coarser than the original brief's list (four codes, not a distinct
   `insufficient_hours`/`unavailable_people`).

---

## Walkthrough for Arch

**What you can do through the browser today** (`https://tempo.ensemblesolutions.com.au/`, sign in as
the demo tenant admin):
1. `/data` → upload master data by CSV (workers, work standards, process templates/steps, orders,
   rates, shifts, equipment, constraints — the full list in §3/§4.1), or by XLSX workbook (the
   `XlsxUploadWizard` on the same page's "Load data" tab — pick a file, review the per-sheet preview,
   "Load N sheets").
2. `/runs/new` → run type `order_fulfillment`, enter site ID(s) and a planning window, optionally tick
   "commit this plan" (reserves the workers/order quantity it allocates) → Create run.
3. `/runs/:runId` → see the structured result: per-order steps, release/completion times, shortfall
   quantity and reason, KPIs (paid/productive hours, cost), `feasibility`, `missing_evidence`,
   `operating_hours_violations`, `orders_outside_horizon`. A draft run offers "Commit this plan"; a
   committed run offers "Release this commitment"; each order gets a lifecycle panel (outstanding/
   committed/available-for-planning/fulfilled quantities) with a "Confirm completion" action.
4. The same flow for any of the ten forecast-driven run types, plus the existing roster/attendance/
   reporting/billing/admin modules described in §7.

A worked example of every call these actions make, including the exact request/response shapes, is in
`order-driven-planning.md`'s "Walkthrough" and "Shared-resource conflicts and remaining browser
workflows" sections and this branch's test files (`tests/test_xlsx_import.py`,
`tests/test_committed_vs_fulfilled.py`, `tests/test_shared_resource_conflicts.py`).

**Steps needed for full acceptance** (in priority order, matching §10's gap list):
1. Supply the actual v1/v2 workbook files so source-file compatibility can be tested and confirmed,
   not just fixture-tested support.
2. Decide the order-driven vs. forecast-driven demand (not resource) interaction policy for sites that
   might run both demand modes for overlapping windows.
3. Confirm the automatic-actuals-correlation requirement is genuinely out of scope for this release
   (it is currently treated as a documented future enhancement, not a blocker).
