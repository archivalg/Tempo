# Pilot Charter (draft)

Status: **draft, blocked on commercial decisions** — P0-06 requires this
signed before Phase 0 exit. This template is filled in against the
existing demo tenant (`ten_demo`/`site_mel_01`, the seed data
`tests/factories.py::seed_named_roster_scenario` and
`scripts/seed_e2e.py` already use) purely so the shape is concrete; every
field marked **TBD** needs a real answer from the CEO and product owner
(Appendix D: "First pilot customer, site and success measures").

## Scope (§1.2's release boundary, restated per this pilot)

| Field | Value |
|---|---|
| Pilot site | **TBD** — one named warehouse only |
| WMS integration | **TBD**, pending ADR-0005 (default assumption: the existing generic WMS client) |
| Workforce-system integration | **TBD**, pending ADR-0005 (default assumption: Deputy) |
| First writeback action | `publish_roster` against the confirmed workforce system (ADR-0006) |
| Reversal method | Republish prior committed roster version (ADR-0006) |

## Data history required

- At minimum, the historical window `app/solvers/*` need for backtesting
  (Phase 6, MOD-07): demand, attendance, roster, and exception history
  covering enough of a seasonal/weekly cycle for the pilot's forecast
  features to be meaningfully validated. **TBD**: exact window, pending
  the pilot operations owner's data availability.

## User groups

Mapped to the principal types this sprint's `app/models/identity.py`
models — **who specifically** fills each is **TBD**:

| Principal type | Pilot role |
|---|---|
| Tenant user (operations_manager) | Roster publication, recommendation review |
| Tenant user (tenant_admin) | Connector/provider onboarding, policy configuration |
| Tenant user (supervisor) | Attendance exception management |
| Worker | Kiosk clock-in/out |
| Support operator | Ensemble Solutions engineering, under the ADR-0008 grant workflow once approved |

Labour Provider and Customer principal types are **not** assumed present in
the first pilot unless the pilot site actually uses labour-hire workers or
runs a 3PL/customer-facing reporting need — confirm against the real site
before Phase 7 UX-06/labour-provider-portal scoping.

## Success measures

**TBD** — must be agreed with the pilot operator before the shadow-mode
comparison (PIL-03) has anything to measure against. Candidates to put in
front of the pilot operator, drawn from what the platform already computes:
- Forecast accuracy vs. actuals (existing `demand_forecast` KPIs).
- Recommended vs. actual labour cost (existing `named_roster`/`workforce_mix`
  KPIs).
- Coverage percentage and unmet-shift-slot count.
- Planner acceptance/rejection/modification rate (PIL-04) — net new,
  needs a place to record it (Phase 6's MOD-11 planner-override audit).

## Writeback boundary

Per ADR-0006: `publish_roster` only, against one confirmed vendor, only
after PIL-06's read-only threshold and explicit business approval are met.
No other action type goes live in the pilot's first writeback window
(PIL-07's "limited user cohort and rollback window").

## Read-only first pilot plan (PIL-02)

1. **Shadow mode** (minimum observation period **TBD**, recommend starting
   at 4 weeks to cover one full attendance/roster cycle plus buffer):
   Tempo ingests real WMS/workforce data (Phase 3) and produces
   recommendations, but no action is ever executed — `POST /v1/actions`
   stays reachable only in a non-production/UAT environment during this
   window, or is feature-flagged off entirely per ACT-10's kill switch,
   applied here before it's even needed for a live incident.
2. **Reconciliation** (PIL-01): before any model evaluation, reconcile
   source record counts/timestamps/key totals against Tempo's canonical
   ingestion — catches connector mapping errors before they're mistaken
   for model errors.
3. **Evaluation** (PIL-03/04): compare Tempo's recommendations against
   what the pilot site's planners actually decided, and record why a
   recommendation was accepted, rejected, or modified.
4. **Staged writeback activation** (PIL-06/07): only after shadow-mode
   thresholds (from the success measures above, once agreed) are met and
   the business explicitly approves — a limited user cohort, a defined
   rollback window, `publish_roster` only.
5. **Go/extend/stop review** (PIL-10): executive decision, documented
   residual risks and owners either way.

## Dependencies

Everything in this charter depends on the commercial decisions Appendix D
marks "before Phase 0 exit": pilot customer/site selection, and repository
ownership/licensing (a prerequisite to any of this work being clearly
proprietary Ensemble IP, per P0-06's own dependency list).
