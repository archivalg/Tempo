# Order-driven labour planning — scope, Stage 0 assessment, Stage 1–2 approach

Source: Arch implementation brief, 9 Oct 2026 (order-driven workload, task/activity rates, indirect
coverage, dependencies, equipment, congestion/staging, costing). This document is the authoritative
detail behind roadmap M3 for this programme; `docs/roadmap.md` §7 points here. No milestone below is
accepted until demonstrated per the acceptance scenarios in the brief and recorded with evidence.

Status vocabulary matches `docs/roadmap.md`: Partial / Open / Blocked / Accepted.

## Scope decision (9 Oct 2026)

This programme **supersedes and expands roadmap M3** rather than sitting outside the first release.
The roadmap's blanket deferral of "new solver families" (§1, §12) is narrowed: order-driven extensions
to the *existing* warehouse labour solver (process templates, task dependencies, equipment, indirect
coverage, congestion/staging) are in scope under M3. Still deferred: Prime integration, a separate
Maestro service, and unrelated new solver products.

## Stage 0 — code assessment (complete, 9 Oct 2026)

The brief describes Excel workbook schemas (v1/v2) as the reviewed field contract. Current Tempo does
**not** import Excel workbooks at all — the live importer (`services/tempo-api/app/imports/`) is a
single CSV, contract-driven pipeline (`CONTRACT_VERSION = "1.0"`, `contracts.py`) covering four data
classes (master, forecast, transactions, bulk). The workbook sheets are a useful schema reference, not
a description of deployed Tempo behaviour — treat every "v1/v2" sheet below as a target schema, not an
existing import format.

### Support matrix

| Capability | Accepted/stored today | Validated | Consumed by solver | Visible in UI | Tests | Key citation |
|---|---|---|---|---|---|---|
| Sites/zones/activities/work standards (seconds_per_unit) | Sites/activities yes; Zones model exists but no import path | Yes (sites, work standards) | Yes (`labour_requirement.py:82`) | Data/Demand pages | `test_imports.py` | `contracts.py:57-67` |
| Workers/availability/pay rates (employment_type+role only) | Yes | Yes | Yes | Data page | `test_imports.py` | `apply.py:71-176` |
| Skill level, Activity Roles/zone weights, Labour Providers, Performance, Customer Contracts | Models exist; **no import path** | No | No | No | No | import engine has no CONTRACTS entry for these |
| Demand mode (forecast-only / known-orders / hybrid) | **Absent** — forecast only | — | — | No toggle anywhere (`NewRun.tsx`, `Demand.tsx`) | No | `RunRequest` has no `demand_mode` field (`schemas/runs.py`) |
| Order / receipt entity, due-time, despatch deadline | **Absent entirely** | — | — | No | No | no order model in `app/models` |
| Process templates / task precedence (pick→pack→dispatch) | **Absent** | — | — | No | No | no construct found |
| Per-worker, per-activity rate | **Absent** — worker productivity is one flat scalar (`WorkerPerformanceProfile.productivity_index`); `workforce_mix.py` fixes productivity at 1.0 | — | No | No | No | `team_composition.py:141`, `workforce_mix.py:12-13` |
| Shift templates/patterns as master data | **Absent** — `DEFAULT_SHIFT_CALENDAR` is a code fallback overridable by a policy JSON blob, not an imported entity | No | Fallback only | `PlanningRules.tsx` calendar editor (policy, not import) | `test_shift_calendar.py` (overnight/DST math only) | `shifts.py:22-63` |
| Structured shift breaks (paid vs unpaid) | **Absent** — single `break_minutes`/`breaks_minutes` field, no schedule | No | No (flat `hours_per_worker_per_day` = 8.0 used everywhere) | Attendance only, not planning | No | `canonical.py:114,144`; `policy.py:28` |
| Indirect/fixed headcount coverage | **Absent** — every hour is volume-derived | — | No | No | No | `labour_requirement.py:61-130` |
| Equipment pools | **Absent** | — | No | No | No | no construct found |
| Headcount min/max per activity/shift | Stub — ratio constraints only (`internal_min_ratio`), no absolute min/max | — | Partial | No | No | `workforce_mix.py:86-87` |
| Dependencies (finish-to-start/start-to-start) | **Absent** | — | No | No | No | no construct found |
| Absenteeism uplift in the deterministic plan | **Absent from the real plan** — exists only in the Monte Carlo stress-test (`scenario.py:61-91`) | — | Scenario-only | No | No | — |
| Congestion / off-task capacity loss | **Absent** | — | No | No | No | no construct found |
| Staging/pallet capacity | **Absent** — `ZoneBacklog` is a loose analog, not a capacity constraint | — | No | No | No | `canonical.py:163` |
| Unit conversions | **Absent** — mismatched units are rejected outright, not converted | Rejects, doesn't convert | — | No | No | `engine.py:271-274` |
| Run input immutability/reproducibility | **Partial, self-documented gap** — request params + policy version pinned; live reference data (rates, standards, workers) is not snapshotted, so a completed run is not reproducible after edits | — | — | — | No | `runs.py:44-68` (docstring states the gap) |
| Shortfall reason codes | **Absent** — one free-text `primary_drivers` sentence, no reason taxonomy | — | — | `RunDetail.tsx` dumps raw JSON | No | `workforce_mix.py:216-219` |
| Feasible-with-shortage vs infeasible/failed run | **Broken — dead code** | — | — | — | — | `Feasibility.infeasible`, `RunStatus.failed`, `SolverInfeasible` are defined but **never set/raised anywhere**; a true solver infeasibility raises `InsufficientData`, which rolls back the transaction and **persists no run row at all** (`runs.py:195-201`) |
| Site timezone/calendar handling | **Solid — a genuine strength** | IANA-aware, DST gap/ambiguity rejected explicitly | Yes | — | `test_shift_calendar.py` | `parse.py:86-147`, `shifts.py:66-73` |
| Import validation preview, downloadable errors, upload idempotency | **Solid — already meets the brief's ask** | Yes | — | `UploadWizard.tsx` (accepted/rejected counts, rejected-row download) | `test_imports.py`, `data-import.spec.ts` | `engine.py:92-149`, `UploadWizard.tsx:113-137` |

### Biggest architectural gaps (ranked)

1. No order/task entity — the whole solver stack is period-bucket forecast→hours, not event/deadline scheduling. This is the precondition for every acceptance scenario about due times and shortfall.
2. No per-(worker, activity) rate — productivity is one flat scalar per worker; personal-rate acceptance scenarios cannot be met without this.
3. No process templates/dependencies, equipment pools, indirect coverage, or headcount limits in the solver — these are new constraint classes, not tuning of existing ones.
4. Infeasible/failed-run signalling is dead code today. This must be wired up before order-driven results can honestly distinguish "feasible with shortage" from "solver failed" (required by the brief's UI section).
5. Run snapshots pin request parameters only, not referenced master data — reproducibility of a completed run after later edits is not guaranteed, which the brief's reproducibility acceptance scenario requires.
6. Shift templates/breaks and absenteeism are policy JSON or stress-test-only, not first-class versioned master data consumed by the deterministic plan.

Genuine strengths to build on, not rework: IANA timezone/DST handling, the CSV import validate→preview→apply→undo pipeline with idempotency and upsert-by-key.

## Stage 1 — ingestion, calendars, shifts, breaks, availability (next)

- Add v2 import contracts **alongside** the existing `1.0` contracts (new `CONTRACT_VERSION = "2.0"`
  entries in `contracts.py`, selected per upload, not a replacement) for: Zones, Activity Roles,
  Shift Templates, Shift Breaks (site-scoped), Worker Activity Rates, Skills with `level`,
  Day Rates, Unit Conversions. Existing v1 CSV contracts keep working unchanged.
- Promote shift calendars from a policy JSON blob to versioned master-data rows (new tables), with an
  explicit operating-calendar model (weekday, open/close interval, explicit 24-hour flag) and
  conflict validation against configured shifts.
- Add structured shift breaks (offset, duration, paid/unpaid) and compute elapsed/paid/productive
  hours separately wherever shift hours are used.
- Expand weekly availability + dated exceptions already in the importer to feed the new shift model;
  keep pending leave/RDO requests pending (no behaviour change needed — already correct).

## Stage 2 — order-driven workload, task rates, indirect coverage

- New `Order`/`OrderTask` models plus a configurable `ProcessTemplate`/`ProcessStep` (site/customer
  scoped), with release-no-earlier-than-`order_received` and due-by-`despatch_due` semantics.
- Add `demand_mode` (`forecast_only` / `known_orders` / `hybrid`) to `RunRequest`; hybrid must declare
  whether its forecast is total or incremental demand to avoid double counting.
- Add `WorkerActivityRate` (worker, activity, unit, rate, effective period) with the brief's
  precedence (personal activity rate → compatible personal role rate → weekday activity standard →
  activity standard → legacy `productivity_index` as a last-resort adjustment, never multiplied twice).
- Add indirect headcount coverage (site/role/weekday/time/headcount) as a floor constraint independent
  of throughput, with qualification/availability checks and shortfall reporting.
- Add unit conversion resolution (activity-specific factor → global factor; reject ambiguous paths)
  instead of the current reject-on-mismatch behaviour.
- Fix the dead feasibility/failure path: have the solver set `Feasibility.infeasible` /
  `RunStatus.failed` and persist a terminal run record instead of rolling back with no row, and add
  structured shortfall reason codes (missing_skill / insufficient_hours / insufficient_people /
  no_equipment / headcount_cap / deadline_breach) in place of the single free-text driver sentence.
- UI: add demand-mode selection to `NewRun.tsx`, and replace `RunDetail.tsx`'s raw-JSON dump with
  structured order due-time/completion/shortfall-reason/coverage display for order-driven runs
  (reusing existing `ui.tsx`/`charts.tsx`/`StatusBadge.tsx` primitives per the design system).
- Tests: isolated fixtures per acceptance scenario (deadline planning, process flow pick→pack→dispatch,
  personal rates, unit conversion) — do not combine shortage cases into one fixture.

Stage 3 (dependencies beyond basic precedence, equipment, headcount limits, absenteeism-in-core-plan,
fill priorities) and Stage 4 (congestion/off-task, staging capacity, grade-aware costing, forecast
upgrades) remain **Open**, sequenced after Stage 1–2 land and are demonstrated.

## Stage 1 — delivered (9 Oct 2026)

- New master-data import entities (contract version bumped `1.0` → `1.1`, additive; all v1.0 contracts
  unchanged): `zones`, `activity_roles`, `operating_calendar`, `shift_templates`, `shift_breaks`.
  Validate → preview → apply → undo, duplicate/idempotent-upload protection and upsert-by-key all follow
  the existing importer's pattern (`app/imports/contracts.py`, `validate.py`, `apply.py`, `engine.py`).
- New versioned models + migration `f1a2b3c4d5e6` (tenant+site-scoped RLS, matching the existing policy
  convention): `OperatingCalendarDay`, `ShiftTemplate`, `ShiftBreak` (`app/models/scheduling.py`).
- Operating-calendar conflict validation: equal open/close time, or both 24-hour and closed, is rejected
  outright; a shift template scheduled outside its weekday's operating hours (or on a day marked closed)
  is accepted with a visible warning, never silently accepted or altered.
- Elapsed/paid/productive hours calculation (`app/solvers/shifts.shift_hours`), matching the brief's
  acceptance example exactly: a 22:00–06:00 shift with a 20-minute paid break and a 30-minute unpaid
  break yields 7.5 paid hours and 7h10m productive hours. Equal start/end time is treated as a full
  24-hour shift, never zero.
- Console: the new entities are reachable in the existing generic upload wizard
  (`services/tempo-console/src/components/UploadWizard.tsx`), with plain-language hints.
- Tests: `tests/test_stage1_scheduling.py` (7 new tests) plus the existing `test_imports.py` /
  `test_shift_calendar.py` / `test_solvers.py` / `test_rls.py` suites passing unchanged.

**Explicitly not done in Stage 1** (left for Stage 2+, so as not to overstate this delivery):
- `ShiftTemplate`/`ShiftBreak` are not yet consumed by the solver's daily/roster pipeline — the
  deterministic plan (`workforce_mix.py`, `named_roster.py`, …) still reads the policy-JSON
  `shift_calendar` fallback (`app/solvers/shifts.calendar_from_constraints`). Wiring real shift templates
  into roster generation, and applying `shift_hours` to actual worker assignments, is Stage 2 work.
- Operating-calendar conflict checking only covers same-day (non-overnight) shifts; a full cross-midnight
  calendar check is deferred.
- Worker Activity Rates, Day Rates, Unit Conversions, and Skill `level` import are Stage 2 per the
  brief's delivery sequence, not Stage 1.

## Stage 2 — delivered (9 Oct 2026)

- Fixed a pre-existing Stage 0 finding unrelated to any one stage: `Feasibility.infeasible` /
  `RunStatus.failed` / `SolverInfeasible` were dead code — a genuine MILP/CP-SAT infeasibility
  (`workforce_mix.py`, `named_roster.py`) raised the same `InsufficientData` used for "no input data
  at all", which rolls back and persists nothing. A new `SolverInfeasible` exception now persists a
  terminal, auditable `failed` run with a real reason instead (`app/solvers/base.py`,
  `app/api/v1/runs.py`). Covered by `tests/test_run_infeasibility.py`.
- New order-driven-workload models + migration `a2b3c4d5e6f7` (tenant/site-scoped RLS):
  `ProcessTemplate`, `ProcessStep`, `Order`, `OrderTask` (traceability link), `WorkerActivityRate`,
  `UnitConversion` (`app/models/orders.py`).
- New import entities (contract version `1.1` → `1.2`, additive): `process_templates`,
  `process_steps`, `orders`, `worker_activity_rates`, `unit_conversions` — same validate → preview →
  apply → undo pattern as Stage 1, reachable in the console's upload wizard.
- New deterministic (non-MILP) scheduling module `app/solvers/order_workload.py`, wired as a new,
  addressable run type `order_fulfillment` (`POST /v1/optimisations/order_fulfillment`):
  - `schedule_activity` / `plan_order_steps`: release/due deadline scheduling per order, matching the
    brief's acceptance numbers exactly (300 units, 09:00→12:00, one picker at 100/hr = 3 productive
    hours and 0 shortfall; moving release to 10:00 = 100 units shortfall under the same resources).
  - Finish-to-start precedence scoped to one order at a time — pack starts at its own order's pick
    completion plus lag; an unrelated order's steps use an independent cursor (never globally
    serialised).
  - `resolve_activity_rate`: personal activity rate → compatible personal role rate → weekday
    standard → activity standard, with `productivity_index` applied only as a last-resort adjustment
    and never stacked with a personal rate.
  - `resolve_order_quantity`: `units` is authoritative when present; `lines` is only converted
    (activity-specific factor, then global) when `units` is absent, and a missing conversion path is
    rejected rather than guessed.
- Tests: `tests/test_stage2_order_workload.py` (9 tests covering all four Stage 2 acceptance
  scenarios: deadline planning, process flow, personal rates, unit conversion) plus
  `tests/test_run_infeasibility.py`; full existing suite re-verified green.

**Explicitly not done in Stage 2** (left for Stage 3+, so as not to overstate this delivery):
- `order_fulfillment` is a new, independent run type — it is not yet wired as a `demand_mode` into
  the existing forecast-driven solvers (`labour_requirement.py`, `workforce_mix.py`, `named_roster.py`),
  so a customer cannot yet combine known orders with a forecast in one roster run (the brief's
  "hybrid" mode). That integration is Stage 3+ work.
- Every worker eligible for an activity is treated as available for the whole planning window —
  availability/roster intersection and multi-order contention for the same finite worker pool
  (equipment-style scarcity) are Stage 3, as is a real indirect-headcount floor.
- Day Rates and Skill `level` import remain undelivered (the brief lists them under Stage 2's "task
  rates" heading but they are lower-value than the order/rate/conversion scenarios above given the
  acceptance criteria; follow-up, not forgotten).

## Stage 3 — delivered (9 Oct 2026, partial)

- New models + migration `b3c4d5e6f7a8` (tenant/site-scoped RLS): `FillPriority`, `AbsenteeismRule`,
  `Equipment`, `HeadcountLimit` (`app/models/constraints.py`).
- New import entities (contract version `1.2` → `1.3`, additive): `fill_priorities`, `absenteeism`,
  `equipment`, `headcount_limits` — `headcount_limits` rejects `min_headcount > max_headcount` at
  import time, per the brief's explicit requirement.
- New pure, tested calculation module `app/solvers/constraints.py`:
  - `resolve_absenteeism`: most-specific-first resolution; two rules tied on specificity for the
    same scope raise `AmbiguousAbsenteeismRule` rather than silently picking one.
  - `scheduled_hours_for_absenteeism`: `H/(1-a)` exactly as specified (9 productive hours at 10%
    absence → 10 scheduled hours).
  - `check_equipment_capacity`: sweep-line concurrency check across arbitrary overlapping intervals
    — three trucks correctly block a fourth simultaneous user even across non-identical, overlapping
    shift windows.
  - `check_headcount_limit` / `fill_priority_key`: bounds checking and priority-sort helpers, ties
    preserved as equal (never inferred as ranked).
- Tests: `tests/test_stage3_constraints.py` (9 tests, one per acceptance scenario above).

**Explicitly not done in Stage 3** (left open — this stage is partial, not complete):
- None of `app/solvers/constraints.py` is wired into `order_workload.py`'s per-order scheduling yet.
  Today `solve_order_fulfillment` still treats every eligible worker as available for the whole
  window with no absenteeism buffer, no equipment check, and no headcount cap — these functions are
  ready to be called from there but that integration has not been done.
- Dependencies beyond the Stage 2 finish-to-start-with-lag precedence (start-to-start, cycle
  detection across a full dependency graph) are not implemented.
- Fill priorities are not yet consulted by any solver's objective — "lower numbers first" ordering
  exists only as a standalone sortable function.

## Stage 4 — delivered (9 Oct 2026, partial)

- Extended `LabourCostRule` (additive, nullable columns, migration `c4d5e6f7a8b9`) with
  `position_grade`, `provider_id`, `effective_from`/`effective_to`, so a grade- or provider-specific
  rate can coexist with the existing general (labour_type, role) rate — existing `rates` imports are
  completely unaffected; the new `grade_rates` import entity populates the new columns only.
  Award/position names are treated as identifiers for rate selection, never as an award-compliance
  calculation, per the brief.
- New models `ProductivityLoss`, `StagingCapacity`, `StagingMovement` (`app/models/stage4.py`) and
  import entities `productivity_loss` (rejects a row that gives both or neither of `percent_loss` /
  `off_task_hours`), `staging_capacity` (zone must already exist), `staging_movements` (zone must
  already have a capacity row, and a movement's unit must exactly match it — a mismatch is rejected,
  never guess-converted).
- New pure, tested calculation module `app/solvers/losses.py`:
  - `apply_congestion` / `apply_off_task_hours`: explicit flat rate/hours reductions — no crowding
    curve inferred from a percentage.
  - `compute_staging_occupancy` / `check_staging_capacity`: running occupancy from initial +
    arrivals − departures; matches the brief's acceptance number exactly (110 + 20 − 5 = 125 against
    a 120 cap, flagged).
  - `resolve_cost_rate`: grade+provider > grade > provider > general rate precedence; returns `None`
    (never an invented 0) when nothing is configured, so the caller can show cost as unavailable.
  - `labour_cost`: confirms the existing Stage 1 `shift_hours` split already does the right thing —
    paid breaks are inside `paid_hours` and are costed; unpaid breaks never were, so they are not.
- Tests: `tests/test_stage4_losses_staging_costing.py` (8 tests, one per scenario above).

**Explicitly not done in Stage 4** (left open):
- None of `app/solvers/losses.py` is wired into `order_workload.py` — congestion/off-task loss,
  staging capacity, and grade-aware cost resolution are not yet applied to an actual order-fulfillment
  run's numbers.
- Forecasting improvements (coverage/quality warnings, seasonal terms) are untouched this pass —
  `demand_forecast.py`'s existing WAPE ≈ 10% limitation (noted in `docs/build-progress.md`) stands.
- Currency handling across mixed-currency grade/provider rates is not exercised by a test.

## Integration increment — one coherent plan (9 Oct 2026)

Stages 1–4 above each delivered data models, import, and tested *standalone* calculation functions,
explicitly **not** wired into a real plan. This increment rewrites `solve_order_fulfillment`
(`app/solvers/order_workload.py`) into a single greedy, interval-by-interval, shared-resource
scheduler that actually consumes most of that earlier work together, so a constraint changing
actually changes assignments/completion/cost — not just a number reported after the fact.

New in this increment: `IndirectHeadcountRequirement` model/import (`app/models/indirect.py`,
migration `d5e6f7a8b9c0`), `ProcessStep.equipment_id`/`zone_id` (additive columns + import fields),
`Worker.position_grade` (additive column, no import path yet — see gaps below).

### Capability matrix (supersedes the Stage 0 table above for everything it covers)

Columns: **Imported** (a CSV path exists) · **Stored** (a model/table exists) · **Tested
independently** (a unit/import test exercises it in isolation) · **Enforced by scheduler** (an actual
`order_fulfillment` run changes its output because of it, proven by an integration test running the
real `/v1/optimisations/order_fulfillment` → `/v1/runs/{id}` path).

| Capability | Imported | Stored | Tested independently | Enforced by scheduler |
|---|---|---|---|---|
| Operating calendar (closed days) | Yes | Yes | Yes | **Yes** — closed weekdays produce zero shift instances |
| Operating calendar (non-24h hours vs. shift conflict) | Yes (warned) | Yes | Yes | No — only checked at import time, not re-checked at solve time |
| Shift templates, overnight handling | Yes | Yes | Yes | **Yes** — `_expand_shift_instances` drives real interval boundaries |
| Shift breaks, paid vs. productive hours | Yes | Yes | Yes | **Yes** — integration-tested exactly (test 4) |
| Availability (leave/unavailable/rdo) | Yes (pre-existing) | Yes | No (no dedicated unit test of the blocking logic) | **Yes** — blocked workers are excluded from every reservation/assignment |
| Personal weekly pattern / start-finish window | No | No | — | No — **not modelled at all**; only point-in-time Availability rows exist |
| Process dependencies (finish-to-start + lag) | Yes | Yes | Yes | **Yes** — integration-tested (test 5a) |
| Release time / despatch deadline | Yes | Yes | Yes | **Yes** |
| Personal activity rates (precedence) | Yes | Yes | Yes | **Yes** |
| Unit conversions | Yes | Yes | Yes | **Yes** |
| Equipment/zone on a process step | Yes (new) | Yes (new) | No (only via integration tests) | **Yes** — integration-tested (test 2b) |
| Indirect headcount coverage | Yes (new) | Yes (new) | No (only via integration tests) | **Yes** — integration-tested (test 3); break-relief *shortfall* path is tested, the *relief-provided* path is not |
| Fill priorities | Yes | Yes | Yes (Stage 3) | Partial — determines which **activity** is served first in an interval; does not yet reorder tasks *within* an activity (that's despatch-due order), and `customer`/`employment_type` scopes are stored but unused |
| Absenteeism (scoped resolution) | Yes | Yes | Yes | **Yes** — integration-tested (test 4) |
| Shared equipment pools | Yes | Yes | Yes (Stage 3) | **Yes** — integration-tested (test 2b), plus a sweep-line safety net over every assignment |
| Concurrent headcount limits (max) | Yes | Yes | Yes (Stage 3) | **Yes** — integration-tested (test 1) |
| Concurrent headcount limits (min) | Yes | Yes | Yes (Stage 3, import-time min>max check) | Partial — a below-minimum assignment is *detected and reported* (`headcount_violations`); no integration test proves it, and the scheduler does not refuse to run below minimum |
| Congestion (rate reduction) | Yes | Yes | Yes (Stage 4) | Partial — applied in the rate calculation; **not exercised by an integration test** (only off-task was) |
| Off-task hours (capacity reduction) | Yes | Yes | Yes (Stage 4) | **Yes** — integration-tested (test 4) |
| Staging capacity/occupancy | Yes | Yes | Yes (Stage 4) | **Yes** — integration-tested (test 5b); violations are reported, not yet fed back to re-sequence work away from a full zone |
| Grade/provider/effective-dated cost rate | Yes (`grade_rates`) | Yes | Yes (Stage 4) | Partial — `resolve_cost_rate` is called with the worker's `position_grade`/`provider_id`, but `position_grade` **has no import path**, so a CSV-only tenant cannot reach a grade-differentiated rate end-to-end yet |
| Paid vs. productive hours, total cost | Yes | Yes | Yes | **Yes** — reported in `result.kpis`, integration-tested (test 4) |
| Demand mode (forecast-only / known-orders / hybrid) | No | No | — | No — `order_fulfillment` remains a **separate run type**, never combined with `workforce_mix`/`named_roster`'s forecast-driven demand. This is the largest remaining gap: there is still no single run that plans known orders *and* forecast demand together. |

### Explicitly not done

- **No hybrid demand mode.** This was and remains the single biggest gap against the brief's original
  ask ("plan labour from known orders... while retaining forecasting"). `order_fulfillment` is its own
  run type with its own worker pool accounting; it does not know about `workforce_mix`'s forecast-driven
  headcount, and vice versa — a site running both would double-count or under-count nobody-knows-which
  workers if both were run for overlapping windows today. Treat them as mutually exclusive per window
  until this is addressed.
- **Personal weekly availability patterns** (earliest_start/latest_finish per weekday) are not modelled;
  only point-in-time Availability (leave/unavailable/rdo) rows are. The brief's "a 06:00–14:00 personal
  window cannot accept 14:00–22:00" scenario is not implemented.
- **`position_grade` has no import path.** It can only be set by direct database access today, so
  grade-differentiated costing is reachable in tests but not from a CSV upload.
- **Fill priority** only orders which *activity* a shift's capacity serves first; it does not reorder
  individual tasks within one activity (despatch-due order is used there) and the `customer`/
  `employment_type` scopes are inert.
- **Shortfall reason codes** are coarser than the brief's list: `missing_skill` / `no_equipment` /
  `headcount_cap` / `deadline_breach` (the last used as the default/catch-all). There is no distinct
  `insufficient_hours` or `unavailable_people` code.
- **Staging violations do not feed back into scheduling** — a zone over capacity is reported, but the
  scheduler does not hold back or reroute the work that caused it.
- **Congestion** is applied in the rate math but has no integration test proving it changes a real run
  (only `off_task` does).
- The scheduler is a **greedy, non-MILP, interval-granularity** allocator: a dependent step cannot start
  until the *next* shift instance even if its predecessor finishes with time to spare in the same
  instance (documented simplification, not a bug — see `order_workload.py`'s module docstring).

## Ledger

| Item | Status |
|---|---|
| Stage 0 code assessment | **Accepted** — this document, 9 Oct 2026 |
| Roadmap M3 supersession | **Accepted** — `docs/roadmap.md` §7 updated 9 Oct 2026 |
| Stage 1 (calendars/shifts/breaks/v1.1 import contracts) | **Partial** — now enforced by the scheduler (see capability matrix); non-24h operating-hours conflicts are still import-time-only |
| Stage 2 (orders/process templates/task rates/unit conversion) | **Partial** — deadline scheduling, personal rates, process precedence, unit conversion, equipment/zone on steps and indirect coverage are now enforced by one scheduler; hybrid forecast+order demand mode remains open (the largest gap) |
| Stage 3 (fill priorities/absenteeism/equipment/headcount limits/dependencies/indirect coverage) | **Partial** — absenteeism, equipment and max-headcount are enforced and integration-tested; fill priority only orders activities (not tasks within one), min-headcount is detected but untested, dependency cycle detection remains open |
| Stage 4 (congestion/staging/costing/forecast) | **Partial** — off-task loss, staging capacity and paid/productive costing are enforced and integration-tested; congestion is enforced but untested, grade-aware costing has no import path for `position_grade`, forecasting improvements are untouched |
| Integration increment (one coherent plan) | **Partial** — `tests/test_integration_order_schedule.py` (9 tests) proves constraint-driven changes, no double-booking of workers/equipment, indirect-coverage exclusivity, no double-deduction of losses, dependency/staging feasibility impact, clear warnings for missing inputs, and persisted infeasible runs — against the real run-creation path. Full backend suite re-verified green. Remaining gaps are listed above, not hidden. |
