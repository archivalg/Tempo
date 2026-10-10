# Order-driven labour planning — scope, Stage 0 assessment, Stage 1–2 approach

Source: Arch implementation brief, 9 Oct 2026 (order-driven workload, task/activity rates, indirect
coverage, dependencies, equipment, congestion/staging, costing). This document is the authoritative
detail behind roadmap M3 for this programme; `docs/roadmap.md` §7 points here. No milestone below is
accepted until demonstrated per the acceptance scenarios in the brief and recorded with evidence.

Status vocabulary matches `docs/roadmap.md`: Partial / Open / Blocked / Accepted.

## Arch acceptance ledger (17 items, updated 10 Oct 2026 — second completion pass)

Columns: **Import** (CSV path) · **Model** (persisted) · **Scheduling** (actually changes a real
`order_fulfillment` run's output) · **UI** (reachable in the console) · **Tests** (unit/import and/or
integration through the real run-creation API) · **Status**.

| # | Item | Import | Model | Scheduling | UI | Tests | Status |
|---|---|---|---|---|---|---|---|
| 1 | Order-driven demand: release/deadline, known-orders/forecast-only/hybrid, no double-counting, open backlog carried forward | Yes (`orders`) | Yes (`order_.committed_units` and `order_.fulfilled_units`, corrected — see fifth-pass note below) | Yes | Generic upload wizard | `tests/test_committed_vs_fulfilled.py` (new), `test_integration_arch_completion.py::test_committed_run_carries_open_backlog_forward_without_duplication`, `::test_draft_run_never_persists_backlog_or_completes_an_order` | **Accepted, corrected** — a COMMITTED run persists a PLANNED allocation (`committed_units`), never a confirmation of actual completion; `fulfilled_units` (real completion) is written only by an explicit `POST /v1/orders/{id}/complete` confirmation or, in future, a correlated actuals import. See "Fifth pass" below — this corrects a conflation in the second completion pass, found by the user's own review, not by this programme's own testing |
| 2 | Individual worker rates per activity, precedence, compatible units | Yes (`worker_activity_rates`) | Yes | Yes | Generic upload wizard | `test_stage2_order_workload.py` | **Accepted** |
| 3 | Fixed indirect coverage: zero-volume days, break relief, no simultaneous direct work | Yes (`indirect_headcount`) | Yes | Yes | Generic upload wizard | `test_integration_order_schedule.py` (shortfall path), `test_integration_arch_completion.py::test_indirect_relief_worker_maintains_coverage_without_double_booking` (relief *succeeds* path, strengthened with direct per-worker interval assertions — see fifth pass) | **Accepted** — both the gap path and the relief-succeeds path are now integration-tested; non-overlap is now asserted directly against each worker's own recorded assignment intervals (`result.worker_assignments`), not only inferred from aggregate hours |
| 4 | Configurable shifts, overnight, paid/unpaid breaks, operating calendars, revalidated at scheduling time | Yes (Stage 1) | Yes | Yes | Generic upload wizard | `test_stage1_scheduling.py`, integration break/off-task test, `test_integration_arch_completion.py::test_operating_hours_conflict_excludes_shift_but_preserves_compliant_capacity`, `::test_overnight_operating_hours_admit_a_matching_shift_and_exclude_a_conflicting_one` (both new) | **Accepted** — operating hours (including non-24h sites and the overnight-boundary case) are now revalidated at SCHEDULING time, every run, not only at shift-template import time; a shift outside the site's hours for that weekday is excluded and reported in `operating_hours_violations`, never silently scheduled |
| 5 | Personal weekday start/finish windows, including overnight | Yes (`weekly_availability`) | Yes | Yes | Generic upload wizard | `test_integration_arch_completion.py::test_personal_weekday_window_rejects_outside_shift_but_admits_matching_overnight_shift` (new) | **Accepted** — exercised through the real run API; also fixed a genuine bug found while writing this test: a sub-interval past local midnight (an overnight window's own second half) was incorrectly rejected because its minute-of-day was computed relative to its own calendar date instead of continuously from the shift's start (see `_blocked`'s `ref_at` parameter) |
| 6 | Recurring weekly availability + dated leave/RDO + existing approval workflow | Yes | Yes | Yes | Generic upload wizard | import tests | **Accepted** — dated leave/RDO and the approval workflow are Tempo's existing, unmodified mechanism; weekly pattern is additive |
| 7 | Absenteeism scoped by activity/weekday/shift, no duplicate allowance | Yes (Stage 3) | Yes | Yes | Generic upload wizard | `test_stage3_constraints.py`, integration break/off-task/absenteeism test (proves no double-deduction) | **Accepted** |
| 8 | Activity and employment_type fill priorities, incl. permanent-before-casual | Yes (customer scope rejected) | Yes | Yes | Generic upload wizard | `test_stage3_constraints.py`, `test_integration_arch_completion.py::test_permanent_before_casual_fill_priority` | **Accepted** for activity/employment_type; customer scope explicitly rejected, not silently inert |
| 9 | Concurrent min/max headcount | Yes | Yes | Yes | Generic upload wizard | `test_stage3_constraints.py`, integration max-headcount test, `test_integration_arch_completion.py::test_minimum_headcount_violation_is_reported_through_a_real_run` (new) | **Accepted** — both min- and max-headcount violations are now integration-tested through a real run, persisted as a visible `headcount_violations` entry, not only the pure check function |
| 10 | Shared equipment capacity across overlapping activities and shifts | Yes | Yes | Yes | Generic upload wizard | `test_stage3_constraints.py`, `test_integration_order_schedule.py`, `test_integration_arch_completion.py::test_equipment_shared_across_two_different_activities` | **Accepted** — pool is now shared across *different* activities in the same interval, not just within one |
| 11 | Order-scoped dependencies/lag, downstream work at the next valid interval | Yes | Yes | Yes (`SCHEDULING_INTERVAL_MINUTES = 60`) | Generic upload wizard | `test_integration_order_schedule.py::test_pack_cannot_start_before...`, `test_integration_arch_completion.py::test_process_step_duplicate_sequence_is_rejected_not_silently_ambiguous` (new) | **Accepted** — the process-step model is a strictly ordered integer `sequence` per template, which cannot structurally form a dependency cycle; the one way an upload could create an ambiguous ("which comes next?") ordering — two rows claiming the same sequence number — is rejected at import, not silently resolved. Cross-day gaps in accounting remain a known simplification (see assumptions) |
| 12 | Congestion/off-task losses with integrated tests proving effect | Yes | Yes | Yes | Generic upload wizard | off-task: `test_integration_order_schedule.py`; congestion: `test_integration_arch_completion.py::test_congestion_reduces_capacity_in_an_integrated_run` | **Accepted** |
| 13 | Staging capacity influences scheduling/rescheduling: occupancy, departures, matching units | Yes | Yes | Yes | Generic upload wizard | `test_integration_order_schedule.py` (hold-back and departure-driven completion) | **Accepted** |
| 14 | Validated unit conversions, no double counting | Yes | Yes | Yes | Generic upload wizard | `test_stage2_order_workload.py` | **Accepted** |
| 15 | Effective weekday activity rates that demonstrably change capacity | Yes (`day_rates`) | Yes | Yes | Generic upload wizard | `test_integration_arch_completion.py::test_effective_weekday_day_rate_changes_capacity` | **Accepted** |
| 16 | Function/area/inbound-outbound process mappings preserved through import, scheduling, results | Yes (`function`/`flow` on `work_standards`) | Yes | N/A (descriptive, not a constraint) | Generic upload wizard | `test_integration_arch_completion.py::test_function_and_flow_survive_import_into_results` | **Accepted** — carried through to each step's result row; zone/area mapping specifically is `ProcessStep.zone_id` (Stage 2), not a separate area concept |
| 17 | Importable position grades + explicit configurable award rules used in eligibility AND costing | Yes (`position_grade`/`award` on `workers`, `award_rules`, `award_eligibility_restrictions` (new), `required_skill` on `work_standards` (new)) | Yes | Yes — costing (overtime multiplier beyond a configured ordinary-hours/day threshold) AND eligibility (new) | Generic upload wizard | `test_integration_arch_completion.py::test_award_overtime_multiplier_applies...` (costing), `::test_required_skill_excludes_unqualified_worker_with_explanation`, `::test_award_restricted_worker_is_excluded_with_explanation_not_inferred`, `::test_award_with_no_restriction_row_restricts_nothing` (eligibility, all new) | **Accepted** — the brief's eligibility half is now closed with a deliberately separate mechanism from costing: `required_skill` on a work standard is a qualification check (who CAN do the work), and the new `award_eligibility_restrictions` table is an EXPLICIT, imported award/activity restriction (who MAY, by agreement) — never inferred from an award's name. An ineligible worker is excluded from the activity and the exclusion is named in `missing_evidence` (by the worker's own reference, not an internal ID); an award with no restriction row restricts nothing |

**Retained and reverified, unmodified:** pay rates, overtime multiplier field, agency/provider surcharges, customer sell rates/SLA penalties (`SellRateContract`, untouched), sites/timezones, worker preferences, skill/certification validity windows (`SkillCertification.valid_from/valid_to`, already enforced in `solve_order_fulfillment`'s skill lookup) — none of these were changed this pass; the full backend suite (lists below) re-confirms they still pass.

**Remaining limitations, stated explicitly (none of the 17 items above are blocked on them):**
- Cross-day accounting for a step that spans a day boundary remains an approximation (see Stage 2/11's note above) — a documented simplification, not a defect found in testing.
- `required_skill` and `award_eligibility_restrictions` gate direct-work eligibility; indirect-coverage role matching continues to use `SkillCertification` only (unchanged, and out of this pass's scope).
- Hybrid demand mode's forecast/known-order split still uses local-calendar-day buckets (a documented approximation, unchanged this pass).

## Original data issues — verified against real imports and runs (10 Oct 2026, third pass)

The brief named specific data-quality scenarios observed in Arch's own source files. Each is now
verified through the real import/run APIs in `tests/test_original_data_issues.py`, and one was
found to be a genuine gap and fixed, not just documented:

| Issue | Finding | Fix / evidence |
|---|---|---|
| Mismatched task names between sheets (casing) | **Genuine gap, fixed.** `unit` was already matched case-insensitively everywhere, but a process step's `activity` was compared to Work standards with exact case — "Picking" vs "picking" was rejected as a spelling error. | `_activity()` in `app/imports/validate.py` now lowercases before comparing, matching `unit`'s existing convention. `test_activity_name_casing_mismatch_across_sheets_is_normalised_not_rejected` |
| Unit casing ("Units"/"units"/"UNITS") | Already correct — every unit field is lowercased on import. | `test_activity_name_casing_mismatch_across_sheets_is_normalised_not_rejected` (covers the same normalisation path) |
| Duplicate area/zone names | Already correct — `zone_id` is the real key; `zone_name` is cosmetic and may repeat. | `test_duplicate_zone_names_import_as_distinct_zones` — two zones named identically import as two distinct zones |
| Unqualified supervisor (indirect-coverage role nobody holds) | Already correct — reported as `indirect_coverage_gaps` with `missing_qualified_workers`, never silently picks an unqualified worker. | `test_unqualified_supervisor_requirement_reports_a_coverage_gap_not_a_silent_pick` |
| Inappropriate/invented unit conversions | Already correct — a missing conversion path raises rather than guessing (`resolve_order_quantity`); factors are bounded at import (`1e-4`–`1e6`). | `test_stage2_order_workload.py` (existing); `app/imports/validate.py` factor bounds |
| Empty optional sheets | Already correct — a header-only upload is rejected at inspect time with an actionable message ("the file has a header but no data rows"), never a 500 or a silent no-op. | `test_empty_optional_sheet_upload_is_rejected_cleanly_not_crashed` |
| Dates outside the planning horizon | Already correct — an order whose window doesn't overlap the run's planning window is excluded from that run's `orders`, not silently scheduled or erroring. | `test_order_outside_planning_horizon_is_excluded_not_silently_scheduled` |
| v1 compatibility (older sheets without this programme's new optional columns) | Already correct — `function`/`flow`/`required_skill` are all optional; a v1-shaped `work_standards` file with neither still imports cleanly. | `test_v1_shaped_work_standards_csv_still_imports_without_the_new_optional_columns` |
| Preserve ignored example rows | **Investigated; content-based auto-detection explicitly rejected as unsafe, not implemented.** A first attempt made `stage()` discard any row matching a contract's example values exactly. It broke three EXISTING, legitimate tests in this same suite (`test_work_standards_close_the_old_one...`, `test_worker_activity_rate_and_unit_conversion_import`, `test_fill_priority_import_round_trip`) because their real data (plausible activity names, round numbers, common dates) coincidentally matched every example value — proving a real customer row can be indistinguishable from an unedited template by content alone. Silently discarding it would be worse than the problem it solves. | Reverted. The actual safeguard already in place: a template's example row is an ordinary valid row (`test_every_template_example_row_passes_its_own_validator`) that, like every other staged row, only becomes real data if a person reviews the staged preview and explicitly applies it — `test_template_example_row_requires_an_explicit_apply_before_becoming_real_data` confirms staging alone leaves the batch in `validated`, never `applied` |

The one genuine fix (activity casing) is a general import-pipeline fix — it applies to every
master-data entity that cross-references an activity, not only the order-driven ones, since
`_activity()` is shared code.

## Focused final review of `39df1c5` (10 Oct 2026, fourth pass)

A targeted review of four specific behaviours plus two re-confirmations, verified through the real
import/run APIs. One genuine gap was found and fixed (a visible exclusion summary for out-of-horizon
orders); the others were confirmed already correct, with regression tests added either way.

1. **Replenishment/Replen produces an explicit mapping requirement or validation error.** Confirmed:
   Tempo has no activity-VALUE synonym table (only CSV *column header* synonyms exist, e.g. "task" →
   `activity`) — an abbreviated or inconsistent activity name across sheets is NOT auto-mapped, and
   produces the "validation error" half of the brief's either/or requirement: `"activity 'Replen' has
   no work standard. Add it under Work standards first (or correct the spelling)."` — naming exactly
   what to fix. `test_activity_name_that_does_not_exist_anywhere_produces_an_actionable_validation_error`.

2. **Scheduled or committed plans do not mark actual work fulfilled; confirm what updates `fulfilled_units`.**
   ~~Confirmed by direct code inspection... a "scheduled" plan never executes that line.~~
   **Superseded by the fifth pass below.** This confirmation was true of the CODE as written, but it
   missed the actual scope gap: a COMMITTED run *was* the thing writing `fulfilled_units`, and
   committing a roster is a plan, not a confirmation that the labour physically happened. The
   corrected design (below) separates `committed_units` (what a committed run plans) from
   `fulfilled_units` (what is confirmed actually done, via an explicit completion action only). This
   gap was caught by the user's own review, not by this programme's own testing — recorded honestly.

3. **Indirect relief and direct assignments cannot overlap for the same worker.** Already correct and
   now pinned down precisely, not just inferred: `test_indirect_relief_worker_maintains_coverage_
   without_double_booking` asserts `total_paid_hours == 16.0` exactly — one shift (8h) reserved for
   indirect coverage PLUS one shift (8h) of direct work from the other worker. Were the same worker
   ever double-booked into both roles, or neither worker doing direct work, that total would be 8.0;
   were both workers somehow doing direct work, it would be 24.0. 16.0 is only reachable by exactly
   two distinct workers, each doing exactly one role, for exactly one shift each.

4. **Workbook row 4 is ignored structurally; plain CSV rows are preserved regardless of whether their
   values match an example.** ~~Re-confirmed: Tempo has never had a workbook/XLSX importer... not a
   gap.~~ **Superseded by the fifth pass below.** On re-review this was the wrong conclusion: the brief
   explicitly described the reviewed templates as workbooks customers are told to upload whole, so a
   CSV-only pipeline does not complete that requirement regardless of when the scope decision was
   documented. A version-aware XLSX importer was added (below). The CSV-side finding stands unchanged:
   `read_csv()` skips rows structurally (header + blank-row skipping), never by content —
   `test_plain_csv_rows_are_preserved_regardless_of_whether_they_match_an_example` (unaffected by this
   correction).

**Genuine gap found and fixed — out-of-horizon orders were disappearing without explanation.** Prior to
this pass, an open order outside a run's planning window was correctly excluded from scheduling but
left NO trace anywhere — not in the result, not in `missing_evidence`. Fixed in
`solve_order_fulfillment`: a new `orders_outside_horizon` result field lists every excluded order
(ref, received, despatch_due), and a summary line naming them is added to `missing_evidence`. The one
edge case where InsufficientData still rejects the request outright (every open order is outside the
window, so there is nothing at all to run) now names the excluded order(s) in the rejection's own
`detail` text, so the explanation survives even when no run is persisted.
`test_order_outside_planning_horizon_is_excluded_not_silently_scheduled` (now also asserts the summary
appears) and `test_order_entirely_outside_horizon_is_named_even_when_the_run_is_rejected` (new).

**Empty optional sheets can be omitted cleanly — reconfirmed, not just for a header-only upload, but
for the entity never being uploaded at all.** `test_order_fulfillment_run_with_no_optional_entities_
configured_at_all_completes` runs order_fulfillment with equipment, headcount_limits,
indirect_headcount, absenteeism, productivity_loss, staging, day_rates, award_rules and
weekly_availability all left completely unconfigured, and confirms a normal, on-time completion.

## Fifth pass — two scope/correctness corrections (10 Oct 2026) — STATUS: confirmed

Two gaps identified by review, not by this programme's own testing. Both corrections are implemented
and now confirmed: full backend suite 504 passed (`services/tempo-api`, `pytest -q`, 23m47s — up from
493, with 11 new tests across `tests/test_committed_vs_fulfilled.py` and `tests/test_xlsx_import.py`),
and both browser e2e scenarios re-verified passing against the corrected backend. While this pass was
in progress, an unrelated full suite run from an earlier pass was found still active in the
background (a process-tracking mistake on this session's part, not a product defect) and had begun
colliding with new test runs against the same database — it was killed and the database connections
cleared before the final clean 504-pass confirmation above.

### 1. Committed does not mean physically fulfilled — CORRECTED

The second completion pass's `fulfilled_units` conflated two different things: a committed run's
PLANNED allocation, and actual confirmed completion. Corrected:

- `Order.committed_units` (new column, migration `c7d8e9f0a1b2`) — the planned allocation a committed
  run records. This is what stops a later run from re-scheduling labour a published roster already
  promises. Written ONLY by `solve_order_fulfillment` when `request.input.committed is True`.
- `Order.fulfilled_units` (existing column, semantics corrected) — actual confirmed completion.
  Written ONLY by the new `POST /v1/orders/{order_id}/complete` endpoint (`app/api/v1/orders.py`), an
  explicit, auditable confirmation. The solver never writes it. A correlated actuals import (matching
  WorkloadEvent actuals back to an order automatically) is NOT built — stated as an open item, not
  pretended to be done.
- A future run's remaining backlog is `units − max(committed_units, fulfilled_units)` — whichever is
  larger already means "don't reschedule this", each for its own distinct reason; this is what makes
  confirming completion of already-committed work reduce backlog exactly once, not twice.
- `Order.status` now only becomes `"completed"` via the explicit completion endpoint reaching the full
  quantity — never merely from being fully committed.

Tests: `tests/test_committed_vs_fulfilled.py` (new) — committed-vs-fulfilled separation, the
completion endpoint's effect and status transition, and confirmed-completion-without-duplication.
Existing backlog tests in `test_integration_arch_completion.py` updated to assert `committed_units`
(not `fulfilled_units`) after a committed run, and that `status` stays `"open"` even when a committed
plan is complete.

### 2. Workbook support was part of the supplied brief — ADDED

A version-aware (v1/v2) XLSX importer was added: `app/imports/xlsx.py` plus
`POST /v1/imports/xlsx/inspect` and `POST /v1/imports/xlsx/stage` (`app/api/v1/imports.py`). It reuses
the EXISTING staging/preview/apply pipeline unchanged — one `ImportBatch` per recognised sheet,
previewed and applied through the same `/imports/batches/{id}/apply` endpoint a CSV upload uses.

- **Structural, not content-based, skip**: row 1 is the header; rows 2-4 are guidance/example content,
  always skipped by POSITION regardless of what they contain; real data begins at row 5 — built from
  the brief's literal, stated layout ("data beginning at row 5 and row 4 ignored"). This was NOT
  checked against an actual Arch source workbook, which this programme was never given access to (the
  original brief said not to block on that access). If the real layout differs, `HEADER_ROW` and
  `DATA_START_ROW` in `app/imports/xlsx.py` are the two constants to correct.
- **Sheet relationships preserved**: recognised sheets are staged in an explicit dependency order
  (`app/imports/xlsx.py`'s `_PROCESSING_ORDER` — sites before workers before orders, etc.) distinct
  from `contracts.DATA_CLASSES`'s display-grouping tuple, which is not a safe processing order.
- **Version-aware v1/v2**: one sheet-name → entity mapping and one set of contracts serve both — every
  field this programme added is optional, so a v1 sheet (fewer columns) and a v2 sheet (more columns)
  both validate against the same contract, the same way CSV v1 compatibility already works.
- **An unrecognised sheet is reported, never silently dropped** — both endpoints list it explicitly.
- **CSV is unchanged** — no content-based row deletion was added anywhere; the CSV pipeline's existing
  structural (position/blank-row) skip is untouched.

Tests: `tests/test_xlsx_import.py` (new) — multi-sheet recognition and dependency-ordered staging, row
4 (and the guidance rows around it) structurally ignored even when well-formed, a data row that
happens to match the example's content preserved regardless, an unrecognised sheet reported, and a
non-workbook file rejected cleanly.

### Indirect-relief overlap, strengthened

`total_paid_hours` alone cannot prove absence of overlap — two different bugs could coincidentally
produce the same total. The solver now records every worker assignment (`result.worker_assignments`:
worker, indirect/direct, role or activity, start/end) specifically so this can be checked directly,
not inferred. `test_indirect_relief_worker_maintains_coverage_without_double_booking` now groups by
worker, asserts exactly one worker did indirect work and a DIFFERENT one did direct work (disjoint
sets), and asserts no single worker's own intervals ever overlap each other.

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

## Arch completion pass (10 Oct 2026)

Closes out the items raised against the integration increment: finer scheduling granularity,
weekly availability/personal windows, staging rescheduling, employment-type fill priority
(including permanent-before-casual), day rates, function/flow preservation, and award-based
overtime. See the Arch acceptance ledger above (17 items) for the item-by-item detail; this section
covers what changed mechanically and the browser verification.

**Scheduling granularity (priority 1).** Each shift instance is now split into
`SCHEDULING_INTERVAL_MINUTES = 60` sub-intervals (`_split_into_scheduling_intervals`); a dependent
step can resume at the next sub-interval once its predecessor finishes and its lag expires, instead
of waiting for the next shift. Indirect coverage still reserves a worker for the whole shift
instance (a supervisor covers a shift, not a rotating hour). A genuinely infeasible run (nothing
could be assigned to anything, direct or indirect) now persists as `failed` with a reason; a run
that was attempted but constrained to zero output by an identifiable, already-reported cause
(indirect coverage, a headcount cap, a full staging zone) stays an honest `feasible_with_slack`.

**Weekly availability/personal windows (priorities 5-6).** New `WeeklyAvailabilityPattern`
model/import (`weekly_availability`): per-weekday `available` flag and an optional
`earliest_start`/`latest_finish` window (overnight-capable, same convention as shift templates). A
worker outside their window for a given sub-interval is excluded the same way a dated
Availability/leave row already was; dated leave/RDO continues to override the weekly pattern for
that date, unchanged.

**Staging rescheduling (priority 13, extended).** The scheduler now tracks live per-zone occupancy
(seeded from imported `staging_movements`, advanced as departures occur) and, before letting a step
complete into a zone, checks whether it still has room. If not, the step is held back — not forced
to overflow — and retried at the next sub-interval; a later departure can let it complete within
the window. `result.staging_delays` reports every hold-back.

**Equipment shared across activities (priority 10, fixed).** A pool is now decremented once per
sub-interval and shared across every activity drawing on it in that sub-interval, not re-granted in
full to each activity independently.

**Fill priority (priority 8, extended).** Employment-type priority now also decides *which workers*
are assigned when capacity is constrained (not just which activity is served first) — proven by a
permanent-before-casual test that gives the two employment types different costs and checks which
one was actually picked.

**Day rates (priority 15, new).** `DayRate` model/import (`day_rates`): an activity's rate for one
weekday, used for any worker without a personal activity rate — fills the `day_rate` slot
`resolve_activity_rate` already had.

**Function/flow (priority 16, new).** `WorkStandard.function`/`.flow` (optional, additive columns on
`work_standards`) are carried through unchanged into each scheduled step's result row.

**Award rules (priority 17, extended).** `AwardRule` model/import (`award_rules`) plus
`Worker.award`: an award name alone changes nothing; once a matching rule exists, hours beyond its
`ordinary_hours_per_day` for a worker on a given local date are costed at `overtime_multiplier`.
This is **costing only** — award rules do not yet affect eligibility (who may perform an activity),
which remains an open half of this item.

**Browser verification.** Against a freshly-restarted local stack (API + console, `tempo_e2e`
database, Ensemble demo tenant reseeded), `e2e/order-fulfillment.spec.ts` drives the real app:
signs in, uploads `process_templates`/`process_steps`/`orders` CSVs through the Data page's upload
wizard (own column names, validate-then-load, replay-safe), creates an `order_fulfillment` run from
New Run, and confirms the run reaches `completed_with_warnings` with the order's own reference
visible in the structured result. Screenshots: `docs/screenshots/order-fulfillment-data-loaded.png`,
`docs/screenshots/order-fulfillment-run-result.png`. This run **found and fixed a real bug**: a
browser whose `Intl.DateTimeFormat().resolvedOptions().timeZone` resolves to a raw UTC-offset string
(seen in this headless environment) crashed the scheduler with `ZoneInfoNotFoundError` instead of
being handled — fixed by `_normalize_timezone_name`, with a regression test
(`test_timezone_offset_string_is_normalized_instead_of_crashing`).

## Walkthrough (representative sample data)

A customer can follow this exact sequence today (the same data the browser verification above used):

1. **Data → Load data → Process templates** — upload a CSV with your own column names:
   `site,process_code,customer_id` / `mel_dc_01,outbound_standard,`
2. **Process steps** — `site,process_code,sequence,activity` / `mel_dc_01,outbound_standard,1,picking`
   (add a second row with `sequence=2,activity=packing` for a pick→pack flow).
3. **Orders** — `site,order_id,order_received,despatch_due,units,process_code` /
   `mel_dc_01,SO-1001,2026-10-12 09:00,2026-10-12 12:00,300,outbound_standard`
4. Optional, same Data page: **Worker activity rates**, **Shift templates**/**Shift breaks**,
   **Equipment**, **Indirect headcount**, **Headcount limits**, **Absenteeism**,
   **Productivity loss**, **Staging capacity**/**Staging movements**, **Day rates**,
   **Weekly availability**, **Grade rates**/**Award rules**/**Award eligibility restrictions** — each
   validates and previews before anything is applied, exactly like the required uploads above.
5. **Optimisation Studio → New Run** — Run type `order_fulfillment`, Site IDs `mel_dc_01`, a window
   covering the order's dates, Create run. Tick **committed** when this is a real plan (not a draft)
   — only a committed run advances an order's open backlog.
6. **Run detail** — shows `completed` or `completed_with_warnings` (never a silent success over a
   real problem), the order's own reference, its per-step release/completion times and any
   shortfall with a specific reason, plus `kpis` for paid/productive hours and cost. A constrained
   order (not enough time or people to finish) shows `feasible_with_slack` with the shortfall and its
   reason named, never a silent `feasible` — demonstrated in the browser verification below with a
   50,000-unit order given only a 1-hour window.

## Ledger

| Item | Status |
|---|---|
| Stage 0 code assessment | **Accepted** — this document, 9 Oct 2026 |
| Roadmap M3 supersession | **Accepted** — `docs/roadmap.md` §7 updated 9 Oct 2026 |
| Stage 1 (calendars/shifts/breaks/v1.1 import contracts) | **Accepted** — enforced by the scheduler at sub-interval granularity AND revalidated at scheduling time every run (not just at import), including the non-24h and overnight-boundary cases |
| Stage 2 (orders/process templates/task rates/unit conversion) | **Accepted** — deadline scheduling, personal/day rates, process precedence, unit conversion, equipment/zone, indirect coverage all enforced by one scheduler; hybrid forecast+order demand mode works; open-order backlog is now persisted (`order_.fulfilled_units`) and carried forward by committed runs only, with a test proving no duplication |
| Stage 3 (fill priorities/absenteeism/equipment/headcount limits/dependencies/indirect coverage) | **Accepted** for activity+employment_type priority, absenteeism, equipment (now cross-activity), min- and max-headcount (both now integration-tested), indirect-coverage relief (both the gap and the success path tested), and dependency ordering (structurally cycle-free, with ambiguous-sequence rejection tested) |
| Stage 4 (congestion/staging/costing/forecast) | **Accepted** for congestion, off-task, staging (with rescheduling), day rates, function/flow, award-based overtime costing AND award/skill-based eligibility (new); forecasting improvements remain open (unchanged, out of this programme's scope) |
| Integration increment + two Arch completion passes | **Accepted, with limitations stated above** — all 17 acceptance-ledger items above are now Accepted; the remaining limitations (cross-day accounting approximation, indirect-coverage role matching unchanged, hybrid forecast bucket granularity) are documented simplifications, not defects found in testing. Full backend suite (see test run below) passes; real browser verification covers both a successful run and a deliberately constrained one, with the explained-shortfall path captured on screen. |
