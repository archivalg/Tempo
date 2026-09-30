# Tempo — product build blueprint and agent handoff

Version: 1.2 · 30 September 2026
Owner: Ensemble Solutions · Status: implementation brief for review
Baseline: archivalg/Tempo main at 03e4b58 (local checkout reviewed); Arch's Tempo folder and the production-readiness v1.1 specification.
Product intent: an independently deployable, multi-tenant warehouse labour planning and attendance SaaS. External WMS and workforce-system connections serve Tempo's own workflows.

Approved stack decision (30 September 2026): use PostgreSQL for Tempo in development, test, pre-production and production, with a separate Tempo database and credentials. Match the proven Ensemble/Prime AI software stack and language choices where practical: retain Tempo's Python/FastAPI backend and React/TypeScript frontend, and align supported runtime/library versions and operating conventions after checking the actual Prime AI repository. Migrate away from SQLite as an application environment. Oracle Autonomous Database and VPD are superseded for this build; OCI may still host Tempo without dictating its database engine. Prime integration remains out of scope.

## 1. Mandate and delivery rules

Build Tempo into a complete, polished product that answers: Who should work, where, when, at what cost, and what happened against plan? The primary flow is workload demand → labour requirement → proposed roster → manager adjustment and approval → publication → clock/attendance → live exceptions → actual-versus-plan reporting. The ten existing model families remain available through business-oriented workflows and an advanced model area. Do not invent solver outputs or present a test connector as live.

Use the proven Ensemble application shell, interaction conventions, table quality, tenancy and permission discipline, audit, deployment and support practices already established in the other products. Tempo must have its own brand, deployment, data boundary, security enforcement and product-specific permission matrix. Reuse code only after identifying the actual reusable module and license; otherwise implement the same proven contracts locally. The supplied nine-tile Tempo mark, charcoal wordmark and green/amber/red status palette are the visual source of truth. Reproduce the actual supplied assets, not the generated approximation in the concept images. Integrating Tempo with Prime is outside this build.

Non-negotiable gates: (1) remove caller-asserted identity, (2) enforce tenant and subordinate scope in every API and worker, (3) prove a complete Ensemble Solutions sample flow, (4) protect writeback with approval and reconciliation, (5) verify production infrastructure and recovery before customer data, (6) run a measured one-site pilot before general availability. Existing Phase 0–3 code is partial groundwork, not acceptance of these gates. Freeze new solver families until pilot exit; fix and calibrate existing ones.

### Existing baseline and truthful status

| Area | Preserve and extend | Required correction or completion |
|---|---|---|
| Optimisation | Ten run types: demand forecast, labour requirement, workforce mix, named roster, intraday reallocation, training coverage, leave/RDO, team composition, 3PL margin, scenario. | Customer-configured shift calendars, rates, skills, availability, workplace rules, demand drivers, snapshot reproducibility, model validation and readable explanations. Current forecast is Holt linear, despite the draft strategy's GBM language. |
| Attendance | Native PIN/NFC capture, optional geofence, shifts and supervisor list. | Enrolled kiosk identity, Argon2id PIN storage, abuse controls, correction workflow, worker self-service and live exception processing. No biometric claim until hardware and privacy design are approved. |
| Actions | Validate, approve, execute, reconcile; native roster publication and leave approval. | Real vendor writeback for the chosen pilot or a native-only pilot boundary, source-version checks, kill switch, reversal and evidence. External vendor outcome currently remains unknown. |
| Connections | Deputy, UKG Pro WFM, UKG Ready and illustrative WMS client code, canonical ingestion and credential-reference lifecycle. | Certified vendor sandbox handshake, secret vault, scheduled sync, mapping, health, replay and one selected production route. Registration alone is not a working integration. |
| Platform | Identity tables, AccessScope design, Alembic and integration contracts have been started. | Wire trusted login and resolver into all traffic, database isolation on chosen production database, queue/workers, CI/CD, monitoring and restoration. /setup and X-Tempo-Context are insecure developer scaffolds. |
| UX | Thin React console for runs, actions, onboarding, kiosk, attendance and providers. | Designed roster board, operations overview, approvals, attendance desk, reports, clear status and polished admin. No raw JSON as the business UI. |

## 2. Product structure and first release

Modes: Standalone uses Tempo roster and attendance, with optional kiosk. Overlay reads an existing WFM/T&A system and may publish back only after a vendor-specific approval gate. Both consume the same canonical data and solver contracts. A tenant chooses an operating mode per site; changing mode requires a guided migration and source-of-truth confirmation. Display source and freshness everywhere data influences a decision.

First end-to-end release: one Ensemble test organisation, one Melbourne warehouse, realistic synthetic staff and demand, native attendance and roster publication. This is an internal proving environment. A later external pilot names one warehouse, one WMS, one workforce system and one reversible publication action in a signed pilot charter. The business spec's under-60-second roster, >80% planner acceptance, 15% cost-reduction target, and exceptions within 15 minutes are pilot targets, not promised facts; measure against a jointly agreed baseline. The 15% figure is an aspiration, not a solver test fixture or marketing guarantee.

Navigation: Overview · Demand · Roster Planner · Live Operations · Attendance · Approvals · Insights & Reports · Optimisation Studio · Team & Skills · Data & Connections · Administration. Show only permitted destinations. Keep deep links protected server-side. A worker sees My Shifts / My Attendance / Leave; a provider or customer sees its own finite portal scope. Platform administration is on a separate protected route and navigation context.

### Product capabilities

**Demand and requirements:** ingest WMS work orders, throughput, backlog and forecast drivers; select period/site/customer/activity; show history, actuals, forecast, uncertainty and data readiness; translate units to required hours by versioned work standards and role/zone. Allow authorised manual adjustments with reason, origin and expiry.

**People and capacity:** worker directory, employment type, provider, skills/certifications with expiries, roles, zones, availability, leave, maximum hours, breaks/rest, site eligibility, cost rules and privacy-limited profile. Import and manage identities without allowing a provider to see another provider's workers.

**Roster planning:** create a draft from demand, inspect coverage/cost/risk, compare alternatives, drag or edit assignments with hard-rule validation, record override reasons, submit, approve, publish, version and reverse. Preserve who changed what. A roster with unresolved hard constraints cannot publish.

**Live operations:** current shift, planned versus present versus required, late/no-show, unrostered clock, absence, certification gap, backlog and overtime risk. Assign owner, acknowledge, resolve or escalate an exception; show event age and source latency. Intraday reallocation offers a proposed move and its impact; execute only via approved action controls.

**Attendance:** enrolled kiosk with PIN/NFC, clear clock state, duplicate prevention, offline behaviour defined and tested, supervised correction requests, matched/unmatched roster state, timesheet approval and export. Record geofence evidence only where enabled and permitted; avoid exposing precise location unnecessarily.

**Advanced decisions:** workforce mix, training, leave/RDO, team composition, cost-to-serve/margin and scenarios exposed through tailored forms/results, not a generic JSON run form. Financial margins require a distinct permission. Every result shows baseline, proposal, delta, drivers, warnings, confidence components, data freshness and model/policy versions.

**Reporting:** daily labour pulse, roster adherence, hours/cost variance, forecast accuracy, productivity, overtime, agency mix, absence, skill coverage, customer cost-to-serve and 3PL margin where authorised. Filter by finite allowed sites/customers, compare periods, drill through to source/evidence and export with the same security checks.

## 3. Screens — implementation specification for the three concepts

### 3.1 Operations overview (concept 1)

Audience: operations manager; scoped executive variant. Top bar: actual Tempo logo, organisation/site selector, local date/time and data-as-of, search, notifications, help, profile. Header: “Today at [site]”, site timezone, last refreshed and source status. KPI strip: scheduled workers, clocked in, coverage percentage, forecast/actual work, planned/actual labour cost, open exceptions. Each tile has definition, numerator/denominator, trend basis, timeframe and drill-through; unavailable values say “No verified data” rather than zero.

Main region: hourly demand-versus-capacity chart with actual solid line, forecast dashed band and staffed capacity stepped line; point hover shows units, hours, source, as-of and confidence. A shift-by-zone coverage heatmap uses green = covered, amber = risk, red = shortage and a non-colour icon/label. A compact “Attention now” queue shows no-shows, unrostered punches, certification expiry, backlog surge and connector staleness with severity, age, owner and next action. A roster preview shows today/tomorrow and approval state. A right rail shows recommended moves with impact and “Review recommendation,” never one-click execution.

Interactions: site/date/customer filters persist in URL within authorised scope; chart click drills to demand; exception opens a details drawer with evidence and resolve path; recommendation opens full impact/approval. Empty, loading, partial and stale states must preserve layout and explain why. Executive view aggregates only allowed sites and hides named workers unless explicitly entitled.

### 3.2 Roster planner (concept 2)

Audience: planner, manager, approving supervisor. Layout: week/day switch, date navigator, site, customer/activity/zone filters; left worker/resource column; time grid with shifts as blocks; top demand/coverage band; right insights drawer. Sticky worker headers and time labels. Show job role, skill badge, start/end, break and employment type on each shift; compact view supports large teams. Keyboard and screen-reader alternatives to drag/drop are mandatory.

Build path: select planning window and policy; check readiness; generate a named-roster draft asynchronously; see progress and cancellation; show alternative objectives (“balanced,” “lowest cost,” “best service”) only when computed. Baseline versus proposed cards show cost, hours, coverage, overtime, agency proportion and uncovered work. Highlight every hard conflict (availability, rest, certification, maximum hours, overlap, site eligibility) and distinguish soft preference. Edits immediately recalculate validation and estimated impact, with a visible “re-optimise” path. Save draft/version, compare to prior draft, submit for approval; an approver sees a change diff and source lineage. Publish through validate → approval → execute → reconcile; show pending/unknown distinctly from confirmed. Provide a rollback/re-publish prior version action where supported.

Acceptance: a warehouse planner can prepare and publish a valid weekly roster without raw JSON or database access; all assignments appear once, totals reconcile to detailed shifts, and an invalid or stale draft cannot silently publish. The board remains usable at pilot-sized worker counts and narrow desktop widths. Mobile offers a readable list, not a squeezed grid.

### 3.3 Live attendance and team view (concept 3)

Audience: supervisor; separate worker kiosk display. Header: site and active shift, “expected / present / absent / late / unrostered” counts with definitions. Timeline: scheduled versus actual punch markers, late thresholds, current location/zone if known and shift status. Exceptions list: late, missing punch, early departure, overtime, duplicate clock, unrostered entry, geofence or credential issue. Each has owner, timestamp, evidence, resolution state and correction path. Side panel shows worker detail to entitled supervisors only and a privacy-safe audit trail. Refresh automatically with last-update and reconnect status.

Kiosk: full-screen, tenant/site-bound enrolled device identity; large accessible PIN/NFC entry, clock-in/out confirmation, masked identity, no admin navigation and safe timeout. Worker can see own upcoming shifts after verification. Offline punches, if enabled, must be device-signed, timestamped and reconciled with duplicate/conflict policy; otherwise present an explicit “cannot clock” state and supervisor route. Supervisor corrections never overwrite the original event; create an approval-linked adjustment.

Acceptance: an unrostered punch becomes an actionable exception within the agreed target, a failed connector is shown as stale rather than “all present,” and tenant/site tampering through the kiosk fails. Reconciliation makes the difference between scheduled, punched and approved payable time visible.

### 3.4 Other page contracts

| Page | Required content and actions | Role-specific safeguards |
|---|---|---|
| Demand | historical/forecast chart, backlog by activity, assumptions, work standards, readiness, overrides, snapshot references | only authorised site/customer records; manual assumptions audited |
| Approvals | inbox by type/status/age; impact diff; expiry; approve/reject with reason; execution status and reconciliation | distinct requester/approver where configured; revalidate source and scope before effect |
| Insights & Reports | saved views, filters, chart/table toggle, drillthrough, CSV/PDF export, metric dictionary | exported rows and aggregates use same finite scope; margin/PII gates |
| Optimisation Studio | ten capability cards, business forms, run history, comparison, confidence and version details | advanced policy settings restricted; no free-form solver payload for ordinary users |
| Team & Skills | people, roles, provider, availability, certification expiry, rates and cost-rule history | PII and pay rates separately gated; provider sees supplied workers only |
| Data & Connections | connector catalogue, credential setup, test result, sync schedule, last success, lag, dead letters, replay | secrets never rendered after save; connection actions audited |
| Tenant Admin | company/site/customer hierarchy, users, invitations, grants, policies, branding, notifications, service credentials | cannot grant a permission or subordinate scope beyond own delegated authority |
| Platform Admin | tenant lifecycle, plan/feature flags, environment health, support grants, impersonation-free troubleshooting, global audit, jobs and billing hooks | separate platform principal, MFA/step-up, just-in-time target-tenant grant, immutable trail |

## 4. Design system and experience quality

Create an implementation-ready Figma-equivalent design specification in the codebase: colour tokens, typography, spacing, elevations, iconography, responsive breakpoints and components. Use exact supplied Tempo logo PNG/SVG assets and define approved light/dark variants; charcoal is the primary chrome, status green/amber/red conveys operational meaning, and secondary neutral shades preserve chart legibility. Never use traffic-light colour alone: labels, icons, patterns and tooltips repeat meaning. Charts need descriptive titles, units, period comparison, accessible data table, meaningful empty states and source freshness. Avoid decorative charts with synthetic production values.

Components: application shell/sidebar, top bar, tenant/site switcher, breadcrumbs, data freshness banner, KPI card, trend chart, heatmap, virtualised roster grid, roster shift card, insight drawer, exception row, status badge, filtered table, metric definition tooltip, approval diff, confirmation dialog, form field, date/timezone picker, command/search, notification centre, skeleton/empty/error state and audit drawer. Use consistent loading and optimistic-update rules; destructive/irreversible effects require review and acknowledgement. WCAG 2.2 AA for core tasks, keyboard access, focus visibility and screen-reader labels. Test desktop 1440/1280, tablet and mobile layouts; kiosk at its actual device size. Build the three concept screens with realistic Ensemble sample data and visual regression snapshots before expanding the advanced modules.

## 5. Security, tenancy, RBAC and platform administration

### 5.1 Identity and sessions

Replace /setup, localStorage claims and X-Tempo-Context with trusted OIDC login plus Tempo-owned memberships, roles and grants. Select an IdP compatible with existing Ensemble patterns after inspecting the existing implementation. Token verification checks issuer, audience, signature, expiry, key rotation and revocation. Browser sessions use short-lived access tokens and rotating, revocable refresh sessions in Secure HttpOnly cookies with CSRF protection; never store authoritative roles or tokens in localStorage. MFA for all platform and tenant administrators. Service clients and kiosks have separate audiences/principal types. Tempo login and administration must operate independently.

### 5.2 Scope equation and enforcement

Effective access = active tenant membership ∩ role permissions ∩ finite site grants ∩ applicable customer grants ∩ provider grants ∩ worker-self authority. A tenant, site, customer, provider, worker, run or action ID in a route/header is a selector, never authority. Empty site/customer sets deny access; “all” expands only to the caller's finite authorised set. Use a single server-side AccessScope resolver across list/detail, writes, counts, graphs, search, comparisons, exports, monitoring, background work and audit retrieval. Revalidate active grants at job start, result read, export and writeback. Return non-enumerating 404 for foreign object IDs. API permission checks are authoritative; hidden UI controls improve usability only.

| Principal | Initial permissions | Boundary |
|---|---|---|
| Platform Admin (Trev as initial named administrator) | manage platform tenants, features, support grants and platform operations | no ambient worker-data read; time-bound target-tenant support grant with step-up and reason |
| Tenant Admin | organisation, sites, users/grants, labour rules, connections, devices | own tenant, only delegated finite scopes |
| Operations Manager | demand, team overview, planning, approvals and reports | assigned sites/customers; explicit publication permission |
| Planner | create/edit draft, run optimisation, view cost where entitled | assigned sites; cannot approve own action when segregation enabled |
| Supervisor | live exceptions, attendance corrections, roster view, approval if granted | assigned sites and workers |
| Executive / Analyst | aggregated reporting and model evidence | scoped aggregates; no named worker or margin without grants |
| Worker | own roster, clocking, attendance and leave | self record; device-assisted capture separately bounded |
| Provider / customer user | supplied-worker tasks or customer reports | provider/customer grants intersected with site |
| Kiosk / integration service | narrow device or API scopes | bound tenant and finite site/connection; no interactive admin |

Define a permission catalogue (platform.*, tenant.*, site.*, labour.demand.*, labour.roster.*, labour.approve, labour.attendance.*, labour.worker_pii, labour.rates.read, labour.margin.read, labour.report.export, connection.*, device.*, support.*). Seed roles through migration/config, and test each permission against every route. Model both route entitlement and row-level boundaries. Platform Admin bootstrap must resolve Trev's verified account identity from configured subject/email invitation; do not hard-code a guess of his email, create a default password, or confer global access on matching display name. Provide a one-time, auditable bootstrap command that refuses to run if an initial admin exists or the verified identity does not match. Document recovery by a second authorised administrator.

### 5.3 Data and API containment

Every tenant-owned table has tenant_id; site/customer/provider/worker boundaries appear wherever relevant. Use tenant-aware foreign keys, indexes and constraints. PostgreSQL is the approved database engine. Implement fail-closed PostgreSQL row-level security (RLS) on tenant-owned tables, with request-local tenant and applicable finite subordinate scope set inside the transaction after trusted authorisation. Use FORCE ROW LEVEL SECURITY where appropriate; the API runtime role must not own protected tables, have BYPASSRLS, or use a privileged migration account. Missing/invalid context returns no rows and cannot authorise writes. Application predicates remain mandatory for behaviour and performance; RLS is the independent containment layer. Test deliberately under-filtered SQL, connection reuse, worker jobs, cross-tenant joins and exports using the real runtime database role. Keep Tempo data and credentials separate from Prime AI. Record a PostgreSQL decision that supersedes the draft Oracle topology/VPD ADRs, then revise migrations, configuration, backup and restore runbooks. Separate application, migration and connector identities; secrets in a vault; TLS, least privilege, safe logs and immutable audit. Threat-model IDOR, CSRF, credential stuffing, kiosk abuse, stale grants, cross-tenant joins, export leaks, malicious connector payloads and writeback replay.

API: version /v1, OpenAPI schemas, consistent problem errors with correlation ID, cursor pagination, bounded filters/requests, server-side validation, idempotency on mutations and strict origin/redirect allowlists. Rate-limit by principal and token, not only IP. Signed service credentials are tenant-bound, scoped, expiring, rotatable and revocable; source payloads never choose their own tenant. No public API or page can derive tenant identity from an arbitrary header. Protect webhooks with vendor signature verification where available.

## 6. Domain model and backend contracts

Core entities: Tenant/Company, Site, 3PL Customer, Provider; User, Membership, RoleAssignment, Site/Customer/ProviderGrant, Session, SupportGrant, AuditEvent; Worker, Employment, Skill/Certification, Availability, Leave, CostRule, WorkStandard; DemandObservation, Forecast, Workload, LabourRequirement; ShiftTemplate, Shift, Assignment, RosterVersion, AttendanceEvent/Session/Correction; Connection, CredentialReference, Mapping, Checkpoint, DeadLetter, DataReadiness; Snapshot, OptimisationRun, Result, Recommendation, Approval, Action, Reconciliation, Notification. Separate source IDs and canonical IDs with versioned mapping. Store UTC instants plus IANA site timezone; explicit daylight-saving and overnight-shift rules. Currency and rounding recorded per cost calculation. PII retention, redaction and data deletion procedures are tenant-configured within legal requirements.

Immutable evidence: snapshot material source record versions and hashes, forecast, effective policy and work standards, availability/certification/cost rules, model/solver version, objective, timezone, currency and seed. Completed results are immutable; corrections supersede through new versions. A run never reads mutable current tables after snapshot creation. A replay with the same snapshot/version must meet declared deterministic tolerance. Missing cost/availability/skill data cannot silently become a credible roster; defaults must be explicit, approved per tenant and reflected in confidence/alerts. Do not carry the current $40 fallback or fixed shift calendar into production without signed pilot policy.

Services: app.tempo.* serves UI; api.tempo.* serves authenticated versioned contracts (exact hostnames/environment suffixes to be chosen within Ensemble's DNS); separate API, solver worker/scheduler and connector runtime. Dedicated queues and dead-letter handling with an outbox; durable run statuses queued/running/completed/failed/cancelled/timed_out, progress, retry and cancel. Tempo's connector runtime owns vendor APIs and credentials; solver code reads canonical data only. No other product's service or private tables are needed.

Required API surface: /me/access; tenants/sites/users/grants; workers/skills/availability/leave; shifts/rosters/versions/validation; attendance and corrections; demand/forecasts/requirements; readiness; optimisation capabilities/runs/results/comparisons; recommendations; actions validate/approve/execute/reconcile/reverse; connections/test/sync/health/dead-letters/replay; exceptions; reports/metrics/exports; audit and platform operations. Publish request/response examples, permission requirements, error codes, state diagrams, idempotency semantics and pagination for each. Preserve working endpoints with compatibility adapters where safe; remove dev-only identity endpoints at production build time.

Metric definitions: planned cost = sum approved scheduled paid hours × effective rule (plus applicable premiums/on-costs when configured); actual cost = approved payable attendance × applicable rate; coverage = staffed required hours ÷ required hours with explicit zero-denominator handling; roster adherence = matched attended shifts ÷ scheduled shifts; forecast error as an agreed WAPE/MAE by period/activity; productivity = completed units ÷ paid productive hours with exclusion policy; exception age = current time minus source event time, alongside ingestion lag. Version the definitions, sources, as-of and reconciliation tolerances. Label estimate versus confirmed actual.

## 7. Data, connectors, workflows and controlled action

Canonical ingestion: tenant-bound envelope, schema version, event/source identity, occurrence/ingestion times, source record version, quality status, idempotency key. Backfill by bounded window with resumable checkpoint; incremental webhook or watermark polling; out-of-order and duplicate tolerance; quarantined records with reason, impact and replay. Connection setup wizard: choose source/product line → enter vault-backed credentials → actual vendor handshake → select site mapping → preview mapped records/quality → backfill → reconciliation → activate schedule. Surface credentials-present separately from connection-verified and syncing. Certify exactly one WMS plus one workforce system for the external pilot, chosen by actual customer access; do not silently assume Deputy.

Roster state: draft → ready_for_review → pending_approval → approved → publishing → published/unknown/failed → reconciled, with rejected/cancelled/superseded paths. Changes after approval invalidate approval; source drift invalidates action token. Validate gives an expiring signed payload hash and human-readable impact. Execute requires permission, approved state, same source version, idempotency key and active feature flag. Unknown vendor outcome triggers reconciliation before any retry. Reversal is a separate audited action using a previously confirmed version and actual vendor semantics. Native publication promotes proposed assignments once rather than duplicating rows. A global and tenant kill switch stops new writebacks while keeping read/diagnosis available.

Exception lifecycle: detected → triaged → assigned → resolved/dismissed (reason), with severity based on operational impact. Retain source occurrence and Tempo detection time; deduplicate repeat events, suppress during known stale-source periods, notify assigned supervisors through in-app channel first. Escalation windows and external notifications configurable after pilot. Corrections/leave changes go through approval and audit instead of editing the original event.

## 8. Environments, bootstrap, deployment and observability

Keep separate local, test, pre-production/UAT and production environments with isolated PostgreSQL databases, credentials, domains and service identities. Align deployment tooling with current Ensemble/Prime practice after inspecting the real infrastructure. Build reproducible infrastructure and PostgreSQL migrations, health probes, separate worker/connector processes, TLS, reverse proxy/WAF as appropriate, secure headers, CI gates, image scanning, backup, restore and rollout/rollback. app.* and api.* use separate origins and strict CORS/cookie policy; production DNS and TLS records documented. Logs/metrics/traces correlate source record → ingestion → snapshot → solver → approval → writeback. Dashboards and alerts cover API latency/errors, queue lag, worker failures, source freshness, dead letters, missing punches, unknown writebacks, security denials, database health and backup failure. High-cardinality request records are sampled/aggregated appropriately; retain audit events deliberately.

Environment files: commit safe .env.example for each service with descriptions and validated required values. For initial local/UAT testing, generate saved .env.development.local / .env.uat in an access-controlled secret location outside git and record the exact path, ownership and rotation procedure in the handoff. Never commit live tokens, passwords, cookie keys or worker PINs, or put secrets in the user-facing sample dataset. On start, reject missing/insecure defaults in production. A one-command bootstrap_ensemble_demo creates a tenant named Ensemble Solutions, a Melbourne sample site, customers, zones, roles, synthetic workers, skills, shifts, costs, demand history, forecast, published baseline roster, attendance/exception examples and comparison scenarios. Use an idempotent, versioned seed with manifest and reset/cleanup command restricted to non-production; create the Platform Admin through the verified-identity command above. Clearly label every seeded measure as synthetic. Demonstrate both Standalone and an isolated simulated Overlay connector without false “live” status.

Developer experience: make setup, make migrate, make seed-demo, make dev, make test, make test-e2e, make verify-security (or platform-equivalent) documented with exact prerequisites. CI checks lint/typecheck, migrations, contract, unit/integration, browser flows and security matrix. Development services start with a clean database and no manual SQL. Provide deployment runbooks, backup restoration evidence, secret rotation, incident response, connector replay, stuck run recovery and publication kill switch.

## 9. Delivery sequence and required evidence

Work in reviewable pull requests. For every increment: record current behaviour, schema/API/UI changes, permissions, migration and rollback, test evidence, screenshot where relevant, and unresolved risk. Do not call a phase complete because code exists; demonstrate the listed acceptance in the running environment.

| Gate | Build increments | Exit evidence |
|---|---|---|
| 0 — Ownership and baseline | Confirm repository ownership/licence, private visibility and protected main; pin current baseline; inventory actual Prime shell/security/deploy pattern; record PostgreSQL decision and supersede draft Oracle ADRs; approve remaining architecture decisions and first pilot boundary. | Access review, signed decision log, backlog, baseline test and screenshot record. |
| 1 — Safe standalone foundation | Migrate SQLite application paths to PostgreSQL, OIDC login, sessions, MFA, AccessScope, user/grant admin, platform admin bootstrap, audit, kiosk enrollment/security, app/API origins, tenant-aware RLS. | Forged-header denial; complete principal × route × site/customer/provider/worker IDOR matrix; revoked access blocks queued work; real PostgreSQL runtime-role RLS tests. |
| 2 — Data and Ensemble bootstrap | Migrations, canonical mappings, configurable labour rules, snapshots, sample data, connection setup and health. | One-command seeded environment, source-to-canonical reconciliation, restart/replay, sample scenario exact totals. |
| 3 — Premium UX foundation | Design tokens/components, real login, shell, Overview, Roster Planner and Attendance screens matching §3, responsive/accessibility. | Visual review on seeded data; manager completes core flow without JSON or developer assistance. |
| 4 — Working planning cycle | Demand and work standards, roster generation queue, edits/validation, cost/coverage comparison, approval, native publish, notifications, exceptions. | Complete demand → roster → attendance → variance browser test; reproducible snapshot and no duplicate assignment. |
| 5 — Remaining product modules | Team/skills, leave, mix, training, intraday, scenarios, margin, reports, provider/customer views where selected. | Each model has business form, validated result/explanation, permission and data-readiness test; no invented claims. |
| 6 — Live integration and hardening | Certify selected WMS/WFM against sandbox, schedule/replay, one reversible vendor writeback, model backtesting, security/ops/load and restore. | Vendor evidence, unknown-outcome reconciliation, rollback exercise, planner feasible-results sign-off. |
| 7 — One-site pilot | Shadow run, reconcile input and outputs, measure planner acceptance/cost/coverage/freshness, limited approved publication, review. | Signed UAT, thresholds or accepted exceptions, no critical defects, go/extend/stop record. |

Gates 1–4 are the first substantial build; do not hold the visual product until all ten solvers are recalibrated. Parallel UI work may use clearly synthetic fixtures while the secured API is built, then switch to real contracts before acceptance. No customer pilot or production writeback skips Gates 0, 1, 2, 4 and 6.

### Cross-cutting acceptance matrix

| Test | Expected result |
|---|---|
| User A guesses tenant B run, report, graph, export, action, worker, site or connector ID | no data/side effect/existence disclosure, including async workers and aggregate counts |
| Supervisor has customer grant but no site grant, or an empty grant list | denied; never expands to all sites |
| Platform Admin opens tenant data without a support grant | denied; approved time-boxed step-up grant is logged and expires |
| Worker PIN guessed repeatedly or kiosk device disabled | adaptive hash, limits/lockout, alert, no tenant switch |
| Roster generated from missing rate/skill or stale demand | blocked or visibly degraded per signed policy; no silent default |
| Manager edits approved roster or source changes before writeback | approval/token invalidated and revalidation required |
| Worker/queue dies mid-run; connector duplicates/out-of-order record | durable terminal/retry state and idempotent canonical record, no duplicate publication |
| Vendor write times out after submission | status unknown, reconcile before retry, no false success |
| Connection stale while attendance dashboard displays | conspicuous stale state; counts not presented as verified live |
| Restore and deploy rollback performed | documented RPO/RTO met, migration compatibility checked, audit retained |
| Planner and supervisor use three concept screens at realistic volume | critical tasks complete by keyboard and pointer, accessible and visually approved |

## 10. Handoff instructions for the coding agent

Start here: inspect repository archivalg/Tempo at the pinned baseline and the existing Ensemble implementation for reusable design, security and deployment patterns. Read Tempo Business Specification, Tempo Product Strategy, Tempo AI Labour Optimisation Spec, Tempo_Production_Readiness_Implementation_Specification_v1.1, its handover summary, docs/roadmap.md, docs/phase*-status.md, docs/pilot-charter.md and ADRs. Treat Tempo's standalone requirements as the release authority. The older Prime integration document is background on solver contracts only; do not implement its Prime connector, agent tools, federation or packaging. Supplied Tempo branding is in the Drive folder. Concept images illustrate layout and hierarchy, not verified data or exact logos.

Execution instruction: implement the gates sequentially in the existing Tempo repository. Begin with repository audit, dependency/secret scan, actual Prime design/security/deployment comparison, then a file-by-file change plan. Deliver executable code, migrations, seed/bootstrapping commands, saved local/UAT environment configuration in a protected location, design components, all screens, API contracts, tests, runbooks and deployment evidence. Keep a docs/build-progress.md ledger with requirement IDs, commit/PR, screenshot, test result and gap. Every claimed working feature must be demonstrated through an actual browser and API against the running seeded environment. Do not substitute mock data in accepted customer screens. Do not announce completion from unit tests alone.

Stop-and-escalate decisions: only decisions requiring a named business/infra owner should block dependent work: verified Trev account for privileged bootstrap; actual Prime reference repo/environment access; deployment runtime/IdP after comparison; production DNS names; customer/vendor sandboxes, one-site pilot and workplace/pay rules; retention/RPO/RTO and formal writeback authority. PostgreSQL is approved and does not need re-selection. Continue independent implementation with explicit reversible local assumptions while these are pending. Never manufacture credentials, pilot metrics or production approval.

Deliverables at the end of each gate: running URL/environment, what a user can do, exact tests and evidence, migration/rollback, known limitations, and next dependency. The final handoff must include role demo credentials or invitation procedure (no shared secrets), sample tenant reset, a screen-by-screen walkthrough, API docs, operating runbook and release decision record.

## 11. Source register and reconciliation notes

Arch's Tempo working folder: Product Strategy, Business Specification, AI Labour Optimisation Spec, Production Readiness v1.1 and handover; branding assets in the folder and Archive.

Tempo repository, roadmap, console README, Phase 3 status, ADRs.

Production-readiness v1.1 specifies Oracle/OCI as a reference and its draft ADRs recommend Oracle. The owner has now selected PostgreSQL for consistency with Prime AI. Supersede the Oracle/VPD ADRs with a PostgreSQL/RLS decision; retain applicable security outcomes and test gates. OCI hosting remains a separate decision.

The older Prime integration specification describes an optional cross-product route. That route is outside this build. Tempo owns its direct vendor connection and canonical ingestion path for this plan.

The strategy describes GBM demand forecasting, but the repository implements Holt smoothing. The UI and release notes must describe the deployed method accurately; replace it only after backtesting and governance, not by relabelling.

The production-readiness handover calls Phases 0–3 “complete” in a coding sense while expressly leaving repo protection, live identity, database verification and vendor certification outstanding. Their acceptance gates remain open.
