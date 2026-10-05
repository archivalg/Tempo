# Tempo UI route checklist

Updated: 2 October 2026

Scope: `services/tempo-console` on `build/tempo-standalone-gate1`. This checklist records visual/interaction status only; roadmap acceptance still follows `docs/roadmap.md`.

| Route | Current condition | Required visual / interaction changes | Status | Browser evidence | Remaining dependencies |
|---|---|---|---|---|---|
| `/` Overview | Uses shared shell, KPI cards, source freshness, chart, heatmap, attention queue and drawers. | Keep source freshness visible and avoid misleading zeroes. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Customer data validation and accepted source definitions. |
| `/demand` Demand | Uses shared header, charts, tables, readiness and override panels. | Maintain forecast provenance and override approval clarity. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Customer samples, supplied forecast acceptance, broader work-standard setup. |
| `/roster` Roster Planner | Shared workflow controls, version steps, board, conflicts, drawer editing and publish/approval actions. | Continue improving narrow/mobile list behavior; keep keyboard form route. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Overnight/break rule completion and realistic-volume UAT. |
| `/live` Live Operations | Shared live KPIs, timeline, exceptions, source freshness and detail drawer. | Preserve stale-source suppression and clear owner/resolution states. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Real connector freshness and operational alert policies. |
| `/attendance` Attendance | Shared KPI strip, filters, timesheet table, correction/approval drawer and export action. | Keep original punches separate from corrections and payable hours. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Complete break/missed-punch policies and payroll export agreement. |
| `/approvals` Approvals | Shared approval inbox, roster steps and decision drawers. | Maintain requester/approver segregation and impact diff clarity. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Broader approval types and source drift revalidation. |
| `/reports` Reports | Shared KPI cards, metric definitions, source freshness and detailed table. | Keep planned/estimated/confirmed labels and future-day dashes. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Customer validation of cost/payable-time policies. |
| `/data` Data | Shared tabs for checklist, upload, history, status and API credentials. | Keep CSV/API state flow explicit and errors recoverable. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Background jobs, availability/rate imports and source-system reconciliation. |
| `/onboarding` Connections | Reworked to shared cards, tables, pending-credentials banners and kiosk credential enrolment. | Distinguish registration from verified/live sync. | Enhanced shell | Blocked: local Chromium crashes at launch in this sandbox. | Deputy credentials/mapping/sync and second vendor selection. |
| `/providers` Team & Skills | Reworked to shared page shell, provider table, scoped supplied-worker table and certification forms. | Keep provider scheduling read-only. | Enhanced shell | Blocked: local Chromium crashes at launch in this sandbox. | Full worker directory, availability, rates and offboarding. |
| `/admin` Administration | Shared device and user admin sections. | Continue separating device enrolment from customer admin. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Branding, policies and full tenant admin module. |
| `/billing` Plans & Billing | Shell added with indicative plan model and no live payment claims. | Add entitlement and payment API once built. | Shell only | Blocked: local Chromium crashes at launch in this sandbox. | Approved pricing, Stripe products, manual entitlement records. |
| `/help` Help Library | Shell added with task links and API reference discovery. | Add article content as workflows stabilize. | Shell only | Blocked: local Chromium crashes at launch in this sandbox. | Full help content and environment-specific OpenAPI links. |
| `/platform` Platform Administration | Shell added with platform boundary and support-access guidance. | Keep platform identity visibly distinct from customer login. | Shell only | Blocked: local Chromium crashes at launch in this sandbox. | Platform tenant APIs, support-grant use path and billing ops. |
| `/account` Account | Shared account page for password and MFA setup. | Keep password/MFA states clear and recoverable. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Email provider for self-service reset. |
| `/invite` Invite | Shared card style for invite acceptance. | Preserve expiry and password rule messaging. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Email delivery provider. |
| `/login` Login | Shared login card, password/MFA/dev-local paths and dev auth warning. | Keep production auth configuration explicit. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Real IdP selection. |
| `/kiosk` Kiosk | Dedicated full-screen device surface, large numeric PIN, timeout, outage state and server-ack success. | Added responsive/touch classes and explicit disabled break placeholder. | Enhanced | Blocked: local Chromium and headless shell crash at launch in this sandbox. | Break capture, missed-punch workflow, offline capture decision and app packaging. |
| `/runs` Optimisation Studio | Reworked to shared shell, filters, status table, empty/loading/error states. | Keep advanced functionality secondary to core planning. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | More tailored business forms per model. |
| `/runs/new` New Run | Reworked to shared form card and advanced-run framing. | Keep normal roster generation in Roster Planner. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Async worker and final run catalogue UX. |
| `/runs/:id` Run Detail | Reworked to shared evidence cards and code blocks. | Reduce raw JSON once business result components mature. | Enhanced shell | Blocked: local Chromium crashes at launch in this sandbox. | Business-form result views for every model. |
| `/runs/compare` Compare Runs | Reworked to shared selection form and KPI table. | Keep permission-gated KPIs hidden. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Saved comparison views. |
| `/actions` Actions | Reworked to shared action-history table and status badges. | Keep writeback state honest. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Real vendor writeback connectors. |
| `/actions/new` New Action | Reworked to shared validation/execution cards with honest overlay warning. | Avoid making unknown outcomes look confirmed. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Vendor writeback implementation and reconciliation scope. |
| `/actions/:id` Action Detail | Reworked to shared evidence/reconciliation card. | Keep unknown/partial outcomes prominent. | Enhanced | Blocked: local Chromium crashes at launch in this sandbox. | Vendor outcome reconciliation with real connectors. |

## Browser verification plan

Use the isolated local dev stack (`127.0.0.1:5174` and API `127.0.0.1:8017`) with the Playwright Chromium executable already cached at `/home/opc/.cache/ms-playwright/chromium-1234/chrome-linux/chrome`. Do not reset the live tenant database.

Required screenshot sizes:

- Desktop 1440 x 900.
- Narrow desktop 1280 x 800.
- Tablet portrait 834 x 1112.
- Tablet landscape 1112 x 834.
- Mobile 390 x 844.

Record screenshots under `docs/screenshots/ui-2026-10-02/` and update this checklist with the actual filenames and any defects found. In this sandbox, both cached Chromium binaries failed before page creation (`chrome`: `setsockopt: Operation not permitted`; `headless_shell`: `sandbox_host_linux.cc ... Operation not permitted`), so screenshots must be captured in an authorised environment that permits Chromium process sandbox/socket setup.
