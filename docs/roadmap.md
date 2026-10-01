# Tempo delivery roadmap

Updated: 1 October 2026
Owner: Ensemble Solutions
Delivery branch: `build/tempo-standalone-gate1`
Status: approved product direction; milestones below remain subject to demonstrated acceptance.

## 1. Product direction and scope

Tempo is a focused warehouse labour planning and time-and-attendance product, intended for SaaS delivery. A customer should be able to configure a site, load staff and workload, produce a useful roster, capture attendance and see actual versus planned labour with minimal assistance.

The everyday journey is:

Set up site → import/connect data → forecast workload → generate/edit roster → publish → clock attendance → review exceptions/timesheets → compare plan and actual.

Owner direction on 1 October 2026:
- Keep setup and everyday use simple. Sensible defaults and guided steps come before advanced configuration.
- Complete Tempo's own internal Time and Attendance and browser kiosk.
- Deliver two external workforce/time-and-attendance connections. Deputy is confirmed; the second vendor/product is to be selected.
- Ingest forecast, master and actual data through both CSV and API.
- Actual workload may arrive as individual transactions or bulk totals.
- Keep Tempo independently deployable, using PostgreSQL and the established Python/FastAPI and React/TypeScript stack.
- Provide self-service onboarding and Stripe subscriptions, plus platform-admin tenant creation without Stripe.
- Price by plan, sites and workforce bands with unlimited platform users; retain Arch's proposed figures as indicative until commercially approved.
- Separate app.tempo.* and api.tempo.* origins, provide platform administration with controlled tenant support access, and deliver a full customer help library and Swagger/OpenAPI reference.

This roadmap replaces the older integration-led roadmap as the delivery priority. The product blueprint remains a source of detailed requirements, but its broader portal, advanced module and architecture expansion must follow this focused release scope. Prime integration, a separate Maestro service, new solver families and advanced enterprise portals are outside the first release. Existing connector code under `app/maestro` may be reused inside Tempo without requiring another customer product.

## 2. Current baseline and truthful status

Baseline reviewed: original main `03e4b58`; build branch through `fa32d77`.

| Capability | Current evidence | Outstanding before acceptance |
|---|---|---|
| Demand and optimisation | Existing solver families; weekly forecast pattern and manual overrides added | Customer data validation, supplied forecast route, consistent units/time buckets and configurable work standards |
| Roster workflow | Versioned drafts, editing/drag-and-drop, conflict checks, independent approval, native publish/reconcile and history | Concurrent changes, overnight/break rules, realistic-volume UAT and simple customer configuration |
| Internal attendance and kiosk | Capture, device enrolment, badge/PIN UI, exceptions, approval and supervised corrections have implementation and recorded tests | Complete breaks, missed-punch workflow, device usability/recovery, offline behaviour and payroll-oriented export checks |
| Reports | Planned/attended/payable hours and cost; demand/timesheet/variance CSV export | Validate calculations and drill-through using actual customer data; agree cost and payable-time policies |
| External workforce systems | Deputy/UKG read-side code and a generic handover/client interface exist | Two named live connections, credentials, mapping, repeatable sync and end-to-end vendor verification; real writeback is not yet verified |
| CSV/API ingestion | Canonical ingestion groundwork exists | Customer-facing import flow and complete versioned contracts for all three data classes, replay/correction rules and reconciliation |
| Accounts and database | Password accounts, sessions, invitations, administrator MFA, tenant/site boundaries, PostgreSQL migrations | Repeatable customer provisioning, delivery of invites/reset links, remaining boundary checks and SaaS operations |
| Verification/deployment | Ledger reports 303 API tests and 18 browser tests; these were not independently rerun during the review | CI, capacity run, exact deployed revision/migration evidence and resolution of conflicting deployment notes |

Implementation is not the same as customer acceptance. Status vocabulary:
- **Partial:** reusable implementation exists but this milestone is not accepted.
- **Open:** work or verification remains.
- **Blocked:** dependent work needs a named external input; unrelated work continues.
- **Accepted:** acceptance criteria passed with a linked commit, running environment and evidence.

No milestone in this revised roadmap is marked accepted. `build-progress.md` retains historical evidence, including stale claims; reconcile those claims before treating them as current deployment status.

## 3. Delivery sequence

| Milestone | Outcome | Initial status | Dependency | Proposed responsibility |
|---|---|---|---|---|
| M0 | One accurate build/deployment baseline | Open | Repository and host access | Engineering |
| M1 | Guided setup and working CSV/API ingestion | Partial | M0; source samples and field definitions | Engineering + customer data owner |
| M2 | Complete internal T&A and kiosk | Partial | M1 worker/site setup; agreed attendance rules | Engineering + operations owner |
| M3 | Simple reliable planning and reporting | Partial | M1 workload + M2 attendance | Engineering + warehouse planner |
| M4 | Deputy connected and verified | Partial / blocked on sandbox | M1 contracts; Deputy credentials | Engineering + Deputy account owner |
| M5 | Second workforce system connected and verified | Blocked on vendor choice | Vendor/product selection and sandbox | Trev/product owner + engineering |
| M6 | Self-service onboarding, Stripe/manual plans, platform support, separate origins and documentation | Partial; new requirements open | Core flow stable; DNS, Stripe/email setup and commercial decisions | Engineering + product/platform owner |
| M7 | Customer pilot and release decision | Open | M1–M6 accepted for release scope | Product owner + pilot customer |

M2 and M3 can progress alongside Deputy work once shared contracts are agreed. Selection of the second vendor must not stop native T&A, CSV/API ingestion or Deputy implementation. These milestones are delivery order, not promised dates. Estimate effort after M0 and sample-data review.

## 4. M0 — establish the working baseline

- Record branch SHA, deployed backend/frontend revisions, database migration head, active containers and configured ports.
- Confirm the intended App 7 ports: frontend 3007, backend 8007, PostgreSQL loopback 5439. Avoid duplicate temporary stacks on those ports.
- Verify actual HTTPS sign-in and current screens; reconcile the ledger's SQLite, login, HTTPS and unapplied-migration statements.
- Remove the tracked machine-specific `.venv` symlink and document repeatable local/test setup.
- Add GitHub CI for appropriate API, frontend build and browser checks using isolated PostgreSQL test databases. Run capacity checks separately with recorded limits.
- Update README and progress ledger links to this roadmap, distinguishing historical implementation claims from current acceptance.

Acceptance: one authoritative deployment record, reproducible checks and a smoke-tested core flow. No source or test task may reset the live tenant database.

## 5. M1 — easy customer setup and data ingestion

### Guided setup

Provide a short checklist: organisation → site/timezone → staff → shift templates/basic rules → workload/work standards → first roster. Allow CSV or external connection for staff; remember mappings and defaults. Show missing inputs in plain language, with sample templates and a safe preview before import. Customer setup must not require SQL, raw JSON or developer-owned configuration.

Minimum master data: sites, workers, employment types, roles/areas, skills or certifications where required, availability, rates and work standards. Start with one site and a useful sample configuration; the data model remains tenant/site aware.

### Data classes and supported channels

| Data class | CSV | API | Required meaning |
|---|---|---|---|
| Master data | Initial load and incremental updates using saved templates | Bulk upsert and incremental changes | Stable source IDs, active/inactive state, effective dates, site/worker relationships |
| Forecast data | Expected workload by date/period, site and activity | Bulk forecast submission and incremental revisions | Forecast version, horizon, units, generated-at and origin; distinguish customer-supplied from Tempo-generated |
| Transactional actuals | Batch of individual operational events | Individual events or batches | Source event ID, event time, site/activity, quantity/unit and correction/version semantics |
| Bulk actuals | Hourly, shift or daily totals | Period-total submissions | Exact period boundaries, grain, dimensions, units, completeness and replace/upsert semantics |

Forecasts include planned work volumes, not just historical demand. Users choose a customer-supplied forecast or Tempo-generated forecast for the planning period and can see its provenance. A revised forecast flags affected drafts for review; it must not silently rewrite a published roster.

Keep workload actuals distinct from labour actuals. Workload actuals measure units processed; labour actuals are roster, punch or timesheet records from native T&A or an external workforce system. Both feed reporting using explicit definitions.

### Shared CSV/API behaviour

- Publish versioned templates/contracts with field names, required values, examples, units and timezone rules.
- Map customer fields to Tempo's canonical model; store reusable mappings per connection/data class. Do not build a general-purpose ETL designer.
- Validate before applying data: types, required fields, known sites/workers/activities, time ranges, duplicate keys and units.
- CSV flow: upload → map → validate/preview → confirm → results with accepted/rejected counts and downloadable row errors.
- API flow: scoped service credential → validate → ingestion receipt/job ID → status and row errors. Define single-record and batch limits; larger accepted batches run durably in the background.
- Derive tenant access from authenticated identity; validate supplied site/source identifiers within that scope.
- Use tenant + source + external ID for source mappings so different customers can reuse the same source IDs.
- Replayed events or files must not double-count. Keep import/batch identity, source revision and reconciliation totals.
- Define updates, cancellation, reversal and out-of-order handling. Preserve correction history; never silently drop or overwrite accepted operational evidence.
- Bulk uploads must declare whether they replace a defined slice or upsert totals. Reject ambiguous replacement scope.
- Avoid counting the same workload twice when transactional and bulk actuals cover the same period: choose authoritative source/grain per site/activity/period; any fallback must be explicit and visible.
- Preserve customer/activity/site dimensions. Aggregate finer actuals only under documented completeness, unit and timezone rules.
- Show last success, period covered, data freshness, rejected rows and missing mapping instructions in one simple Data page.
- API integrations support credential rotation, bounded requests, useful error responses and retries. Record schema/source versions and import audit.
- Define safe import undo/correction for the last batch where practical; dependent published rosters remain unchanged.

Acceptance:
1. A new tenant loads staff/master data, supplied forecasts and actual workload by CSV without developer intervention.
2. The same datasets arrive through API and produce equivalent canonical totals and reports.
3. Transaction and bulk replay/correction tests prove no duplicate workload.
4. Unknown references, mixed units, missing periods, foreign-tenant IDs and partial batches produce actionable results.
5. Overnight and daylight-saving boundaries are verified.
6. Source totals reconcile to accepted records and period totals.

Inputs needed: representative forecast/master/transaction/bulk files and their business definitions. Templates and independent development continue while customer samples are pending.

## 6. M2 — complete internal Time and Attendance and kiosk

Tempo must work for a customer without an external T&A system.

### Internal Time and Attendance

- Manage worker badge/PIN enrolment, active status and site eligibility through the UI.
- Capture clock-in, clock-out, break start/end and current state with clear confirmation and duplicate prevention.
- Configure paid/unpaid break treatment, basic rounding and missing-punch handling as explicit site policies. Keep original punches and separate approved adjustments.
- Match attendance to published shifts, including overnight shifts; label unrostered attendance.
- Provide a supervisor's daily list for late/no-show, open sessions, missing punches, unexpected attendance and excessive hours.
- Allow reasoned correction requests and authorised approval/rejection, preserving actor/time/original evidence.
- Show worked, break and approved payable hours separately. Reopening approved timesheets creates a recorded revision.
- Export approved timesheets in an agreed CSV format suitable for payroll import. Tempo's first release is not a payroll calculation or award-interpretation engine.
- Build on existing approval and correction controls; keep routine review in one simple attendance workspace.

### Browser kiosk

- Full-screen tablet/browser mode, enrolled to one tenant/site, using badge + PIN initially.
- Large touch controls, masked worker confirmation, clear clock/break choices and automatic return to the start screen.
- Display connectivity and successful server acknowledgement; never imply an unreceived punch was recorded.
- Support device disable/re-enrolment, safe session recovery, PIN reset by authorised staff and lost-device handling.
- For the initial release, use online-only capture with a clear cannot-clock message and supervisor correction route during an outage. Offline queued capture is a separately accepted enhancement if the pilot requires it.
- Verify repeat taps, concurrent punches, browser refresh, network failure, device suspension, timezone changes and touch-device usability.
- NFC can follow a verified hardware/use case. Biometrics, mandatory GPS tracking and dedicated native mobile apps are deferred.

Acceptance: real-device/browser tests cover clock/break cycles, overnight work, duplicate taps, missed-punch correction, approval and export; original evidence remains intact; kiosk users cannot reach manager screens.

## 7. M3 — simple planning and actionable reporting

- Translate selected workload forecast into required hours using visible, versioned work standards.
- Configure basic shift templates, availability, skills/site eligibility, maximum hours and rest/break rules.
- Generate a useful draft, explain shortages and cost assumptions, edit and publish through the existing approval/reconciliation path.
- Keep daily actions on a roster board and attendance page. Use clear labels rather than exposing solver names.
- Validate concurrent generation, edits, approval and publication; use appropriate locking/constraints so competing actions cannot create duplicate or stale live rosters.
- Test overnight shifts and adjacent roster windows so publishing one period does not incorrectly retire another period's assignments.
- Report planned hours/cost, attended hours, approved payable hours, late/no-shows and workload per labour hour.
- Explain rates, paid/unpaid time and estimate versus confirmed values. Withhold misleading totals when inputs are missing.
- Provide daily/weekly views, source drill-through and CSV export; avoid adding a dashboard for each existing solver.
- Validate forecast error on held-out periods/rolling history. Synthetic demonstrations do not establish customer savings or accuracy.

Acceptance: a warehouse manager completes a weekly plan and daily attendance review without raw payloads; shift/report totals reconcile; hard conflicts prevent publication; representative team size meets an agreed measured performance target.

## 8. M4 and M5 — two external workforce connections

Deputy is connection 1. Connection 2 is required, with vendor and exact product/version still open. Existing UKG Pro WFM/UKG Ready code is groundwork, not a selection decision. Choose the second system from pilot/customer demand and verified API access.

### Minimum contract for both connections

| Area | Required behaviour |
|---|---|
| Setup | Guided credential/authorisation entry, test connection, site/worker mapping and clear permission errors |
| Read scope | Employees/active status, sites/areas, published rosters and attendance/timesheets; availability, leave, skills and rates where the vendor supports and customer permits them |
| Initial sync | Bounded history import, mapping preview, record counts and reconciliation |
| Ongoing sync | Scheduled incremental updates, pagination/checkpoints, duplicate protection, retry/backoff and reconnect handling |
| Source ownership | Explicit authority for worker master, roster and attendance per site; no simultaneous conflicting clocks or uncontrolled two-way editing |
| Health | Last success, freshness, failed records, next retry and actionable reconnect instructions |
| Verification | Real sandbox/live-test account, source-to-Tempo parity, corrections, clock/timezone behaviour, outages and credential revocation |
| Outbound roster | Defined vendor mapping and verified publication if supported and authorised; otherwise an explicitly accepted read-only connection with CSV handover |

For Overlay sites, existing vendor attendance is the default authority. Native kiosk attendance is enabled only where ownership of workers/time periods is agreed; blending it must not duplicate vendor timesheets.

Implement Deputy first using its existing read-side groundwork. Confirm current vendor API capabilities and permissions during implementation; do not infer them from a generic connector interface. Exercise at least one full planning/reporting flow against real vendor records.

Outbound publication is a separate capability from being connected. Keep review/approval, idempotency, source-version checks and outcome reconciliation. A timeout is unknown until reconciled; operator-loaded CSV is operator attestation, not vendor confirmation. Do not add external attendance/payroll writes to the first release without a customer requirement.

Acceptance for each connector: a customer can connect, map, import, refresh and reconcile without database access; errors are recoverable; no false live/confirmed status. Read-only versus write-enabled scope is recorded. Both connections must pass their agreed scope before a release advertises two supported integrations.

Blocked inputs: second vendor/product decision; account owners, sandbox credentials and permitted data/write scopes. Native product work continues independently.

## 9. M6 — SaaS onboarding, subscriptions, administration and support

Extend the focused product with the minimum customer and platform operations needed to sell, onboard and support it. The following are roadmap requirements, not claims of implemented functionality.

### M6-PLAN — plans and entitlements from Arch's notes

Source: Arch's plan/subscription notes supplied as three screenshots on 1 October 2026. Prices, workforce allowances, annual commitment and add-ons below are indicative proposals. Implement configurable commercial definitions; final prices, taxes, inclusions and contract terms need product-owner approval.

Core commercial model: **Platform + Sites + Workforce Band + optional compute/AI usage + optional modules**. Platform users (planners, managers, supervisors, analysts and executives) are unlimited. Do not charge for login seats or make account sharing attractive.

| Proposed tier | Indicative AUD monthly price per site | Platform users | Indicative annual contract value per site |
|---|---|---|---|
| Essentials | A$1,500 | Unlimited | A$18,000 |
| Optimise | A$3,500 | Unlimited | A$42,000 |
| Orchestrate | A$6,500 | Unlimited | A$78,000 |
| Network | Custom | Unlimited | Custom multi-site agreement |

Annual values reflect Arch's proposed minimum annual commitment, not a decision to bill the whole year upfront. Billing cadence, cancellation and commitment enforcement must be agreed separately.

- Support workforce allowance bands: up to 250 active workers, 251–500, 501–1,000 and 1,000+. Arch's example is Optimise at A$3,500/site/month including up to 250 active workers; do not assume that allowance for every other tier.
- Define active-worker measurement, period, site attribution, duplicate/cross-site treatment and inactive/agency worker handling before billing. Show customers their measured count and allowance.
- Configure plan/version, site count, workforce band, feature entitlements, effective dates and any negotiated discount. Unlimited platform users does not remove role/access controls.
- Agree the feature matrix for Essentials/Optimise/Orchestrate/Network. A commercial tier name does not authorise building new advanced modules or claiming unfinished capabilities.
- Support negotiated multi-site/enterprise discounts through approved commercial configuration.
- Provide a visible allowance warning and agreed upgrade/contact route. Do not silently change bands, charge overages or block clock-out because a workforce limit was exceeded.
- Compute/AI usage and optional modules are future commercial dimensions: reserve configuration only; introduce metering/charges when justified and approved.
- Arch's optional future Tempo Worker mobile module at $3–$5/worker/month remains a separate proposed add-on. Currency and final pricing require confirmation. It does not change unlimited platform users and does not bring a native mobile app into first-release scope.

Acceptance: a versioned plan/entitlement matrix is approved; customers can understand plan/site/workforce allowances; role permissions and subscription entitlements are enforced server-side; manual and Stripe tenants use the same entitlement model.

### M6-ONBOARD — self-service onboarding wizard

Create one resumable wizard shared by customer self-service and platform-assisted setup:

Account/email verification → organisation details → plan/sites/workforce band → Stripe checkout or recorded manual entitlement → site/timezone → staff/master import or connector → workload/forecast and work standards → kiosk/attendance choice → first roster.

- Use sensible defaults, short explanations, import templates, mapping previews and progress indicators. Hide optional advanced settings.
- Allow save/resume, invitation of additional users and clear retry for failed steps.
- Keep commercial/account signup distinct from operational setup so an existing tenant can resume configuration without purchasing again.
- Show payment/provisioning status and a simple readiness checklist for missing data, rates, rules and connector mappings.
- Prevent duplicate organisations/subscriptions on repeated signup, refresh, checkout return or retry. Record provisioning as a recoverable operation.
- Deliver welcome/invitation/reset emails with the correct app URL and next steps through a verified sender.
- A customer should reach a first useful roster without SQL, raw payloads or developer assistance.

Acceptance: browser journeys cover new paid signup, abandoned checkout, returning customer, resumed imports and platform-assisted onboarding; retries do not create duplicate tenants, sites or subscriptions.

### M6-STRIPE — subscription lifecycle

Stripe is the selected payment/subscription integration. Reuse proven Ensemble patterns where suitable, with Tempo-owned configuration and tenant mappings.

- Configure products/prices only after approval of plans, currency, taxes, cadence, workforce/site quantities and annual terms. Keep test/live configuration separate.
- Implement hosted checkout and customer billing management for payment methods, invoices and permitted plan changes.
- Treat verified server-side Stripe events/reconciliation as billing authority; a browser success redirect alone cannot activate paid entitlements.
- Store tenant/customer/subscription mappings and process duplicate or out-of-order webhook events idempotently.
- Cover activation, renewal, failed payment, recovery, upgrade/downgrade, site/band changes and cancellation with agreed effective-date/proration rules.
- Make pending, active, payment-issue and cancelled states understandable. Agree grace/read-only/export behaviour; preserve records and provide an operationally safe attendance path during billing problems.
- Provide platform visibility of billing status, event failures and reconciliation; allow retry without duplicate provisioning.
- Do not store payment-card details in Tempo.

Acceptance: Stripe test-mode lifecycle tests reconcile billing state and Tempo entitlements, including missed/replayed events and recovery. No live charges or price creation are required merely to implement this roadmap.

### M6-MANUAL — platform-created tenants without Stripe

A platform administrator can create a customer organisation and site(s), select plan/version and workforce allowances, apply approved entitlements and invite the first customer administrator without a Stripe checkout or payment card.

- Support manual contract/invoice, pilot, demonstration or complimentary arrangements with explicit billing source, reason, reference, effective/expiry date where applicable and audit actor.
- Manual tenants must not require a fabricated Stripe customer/subscription ID. Keep manual lifecycle separate so Stripe events cannot accidentally suspend or overwrite their entitlements.
- Reuse the operational onboarding wizard and tenant provisioning pipeline.
- Allow authorised plan/allowance changes and suspension/reactivation with clear impact and audit.
- Support an explicit future conversion to Stripe with the customer owner's participation; retain the same tenant/data and prevent double billing.

Acceptance: a platform admin provisions a fully usable non-Stripe tenant, the customer completes setup, and manual entitlements survive unrelated billing events; conversion is tested without data loss.

### M6-ORIGINS — separate application and API URLs

Deploy the customer application at **app.tempo.<approved domain>** and API at **api.tempo.<approved domain>**. These are hostname patterns: the actual domain, DNS records and certificates still need confirmation.

- Configure separate HTTPS origins, gateway routes, frontend API base URL and health/readiness routes.
- Update onboarding emails, invitation/reset links, kiosk links, Stripe return URLs/webhooks and API reference links.
- Configure explicit credentialed CORS, cookie domain/path/SameSite/Secure settings and CSRF handling for the chosen origin relationship.
- Verify browser login, refresh, logout, uploads, exports and kiosk requests across origins without broad wildcard access.
- Keep development/UAT/production hostname and configuration boundaries clear; document redirection/migration from the current hostname.

Acceptance: both approved URLs resolve with valid HTTPS; full browser/API journeys pass on those origins; old links have an agreed transition.

### M6-ADMIN — platform administration and tenant support

Provide a dedicated platform administration page, separate from customer administration, using a platform principal.

- List/search tenants with lifecycle state, sites, plan/workforce allowances, Stripe/manual billing source, onboarding progress and integration/job health.
- Create/invite/suspend/reactivate tenants, manage approved entitlements and view provisioning/billing issues.
- Provide an explicit **Open tenant for support** action. Grant time-bound access to the selected tenant with a recorded reason, authorised role and administrator MFA/step-up, using existing support-grant groundwork.
- Show a persistent tenant/support-session banner and a clear exit/expiry. Tenant switching must discard the previous tenant's data/cache and context.
- Default support access to diagnostics/read-only; separately authorise operational changes, exports or sensitive data access. Preserve the platform operator's identity in every audit event rather than acting invisibly as the customer.
- Record tenant, operator, reason, start/end, granted scope and actions; allow immediate revocation and customer-visible support history where appropriate.
- No unrestricted ambient access to all tenants. Expired/revoked support sessions fail at the API boundary as well as in the UI.
- Keep this a practical support console; do not add broad enterprise administration unrelated to customer operation.

Acceptance: an authorised platform admin opens a specific tenant for support, sees the correct environment and exits cleanly; expiry/revocation/cross-tenant checks pass; manual creation and support actions are auditable.

### M6-HELP — full customer help library and Swagger/API library

Deliver a searchable, versioned help library accessible from the app navigation/profile and contextual page links. Cover all shipped features:
- Getting started and both onboarding routes.
- Plans, workforce allowances and billing.
- CSV templates, mapping, validation errors, corrections and API ingestion.
- Forecast selection, work standards, roster generation/editing/conflicts/approval/publication.
- Kiosk setup, clock/break flow, outages, corrections and timesheet approval/export.
- Deputy and second-connector setup, source ownership, health and troubleshooting.
- Reports/metric definitions, roles, customer administration and support.
- Common problems, release notes and support contact.

Use task-based instructions with verified screenshots/examples; distinguish available, read-only, planned and unsupported features. Keep internal runbooks separate from customer help.

Maintain an OpenAPI schema and Swagger UI on the API origin, linked from an API documentation area. Cover all supported public endpoints with authentication/service credential instructions, scopes, schema versions, sample CSV/JSON payloads, forecast/master/actual ingestion, batch receipts/status/errors, idempotency, pagination, limits, timestamps and correction semantics. Include examples and a downloadable OpenAPI schema. Interactive requests require authorised credentials and must not expose secrets or privileged internal routes.

Acceptance: a new customer can complete setup and common tasks using help alone; documented examples are checked against the running API; Swagger and the schema match deployed supported endpoints; documentation is included in release checks.

### M6-OPS — underlying SaaS operations

- Complete account delivery, tenant/site/service/support boundaries and tenant-scoped source-ID migrations.
- Add durable import/sync/planning jobs with progress/retry/recovery.
- Protect/rotate integration secrets, monitor uptime/jobs, automate backups and off-host retention, and demonstrate restore and deployment rollback.
- Agree and test retention/deletion, customer export, RPO/RTO and availability targets.

Acceptance for M6: customer self-service and platform-assisted non-Stripe onboarding both work; billing/entitlements, support access, separate URLs and help/API documentation pass their journeys; a second customer needs no bespoke code or direct database intervention.

## 10. M7 — customer pilot and release

Pilot one warehouse with agreed workplace rules, workload units, staff data and baseline. Measure:
- Setup effort and assistance needed.
- Time to first useful roster.
- Planner task completion, adjustments and acceptance.
- Clocking reliability and supervisor correction effort.
- Source reconciliation and report accuracy.
- Performance at actual worker/data volumes.
- Connector stability and recovery.
- Labour outcome against an agreed baseline, without promising a fixed saving.

Run the native T&A/kiosk journey and both connector journeys with suitable test/pilot accounts. A customer may pilot a narrower configuration, but incomplete connector work remains visible and prevents advertising the full two-connector release.

Release requires product-owner acceptance of critical tasks, no unresolved critical correctness/isolation defects, tested backup/rollback, documented limits and a supportable onboarding process.

## 11. Decisions and external inputs

| Decision/input | Owner to confirm | Work it affects |
|---|---|---|
| Second workforce vendor and exact product | Trev/product owner | M5 |
| Deputy and second-vendor test accounts/scopes | Customer/vendor account owner | Live connector verification |
| Sample CSV/API payloads and field meanings | Customer data owner + engineering | M1 mapping/parity |
| Attendance, break, rounding, rest and rate policies | Operations/customer owner | M2/M3 calculations |
| Source authority per site/data class | Customer owner | Forecast selection, workload actuals and T&A sync |
| Representative volumes/performance thresholds | Product + engineering | Capacity and UX acceptance |
| Final plan feature matrix, prices, taxes, workforce measurement and annual/billing terms | Trev/Arch/product owner | M6-PLAN / M6-STRIPE |
| Stripe account/test configuration and verified email sender | Platform/account owner | M6-STRIPE / M6-ONBOARD |
| Approved domain for app.tempo.* and api.tempo.*, DNS/certificates | Platform/domain owner | M6-ORIGINS |
| Manual contract policy, support permissions, retention and recovery targets | Product/platform owner | M6-MANUAL / M6-ADMIN / M6-OPS |
| Pilot site, success measures and release boundary | Product + pilot customer | M7 |

Do not stop independent work while a vendor decision is pending. Do not invent credentials, customer policy or acceptance evidence.

## 12. Deferred scope and roadmap maintenance

Deferred: new solver families, complex approval hierarchies, advanced provider/customer portals, a generic integration builder, broad BI studio, full payroll/award processing, biometrics, native mobile apps, offline kiosk capture unless required, Prime integration and mandatory extraction of a separate Maestro service.

Existing advanced solvers remain available behind the core product; expand their UI only when a customer task justifies it.

Track each delivery item using the milestone ID plus task suffix (for example M1-CSV-01 or M2-KIOSK-01). Record owner, status, dependency, commit/PR, acceptance criteria, test/environment evidence and remaining limitation in the progress ledger or linked GitHub issues. Create issues as implementation is planned; this roadmap update itself does not claim issues were created.

Update this file when scope or milestone status changes. Mark accepted only after browser/API or real-connector evidence for the relevant customer journey. Automated unit tests alone do not establish customer readiness.

References:
- [Build progress and historical evidence](build-progress.md)
- [Product blueprint and detailed requirements](Tempo_Product_Build_Blueprint.md)
- [PostgreSQL decision](adr/0011-postgresql-rls.md)
- Original product/business/optimisation documents in the repository are background; current owner direction controls first-release priorities.
