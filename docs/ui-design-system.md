# Tempo UI design system

Updated: 2 October 2026

This guide is the standard for future Tempo UI work. It extends the product roadmap and does not mark any roadmap milestone as accepted.

## Product posture

Tempo is a warehouse labour planning, roster, attendance and reporting SaaS. Interfaces should feel calm, precise and operational. Prioritise clear data provenance, fast scanning and low-friction daily work over decorative dashboards.

Do not fabricate working payments, live vendor connections, confirmed writebacks or customer records. Synthetic data must be labelled synthetic or simulated. A polished shell is still a shell until the API contract and acceptance evidence exist.

## Tokens

Use `services/tempo-console/src/design/tokens.css` for colour, spacing, radius, type, shadows and breakpoints. The Tempo brand source is the supplied logo set under `services/tempo-console/public/brand/`.

- Chrome: charcoal tokens (`--tp-charcoal*`).
- Operational states: green, amber and red from `Tempo Traffic Light.png`.
- Status must be icon plus text. Never rely on colour alone.
- Surfaces use white or near-neutral panels on `--tp-canvas`; avoid decorative gradients.
- Cards use `--tp-radius-m` (8px). Reserve cards for repeated items, panels, tools and modals.

## Components

Use `src/components/ui.tsx` before adding page-specific widgets:

- `PageHead` for title, site/date context and primary actions.
- `Banner` for warning, error and information states.
- `Status` for badges with icon and label.
- `KpiCard` for metrics with definitions.
- `FreshnessBanner` and `SourcePills` for data provenance.
- `Drawer` for focused detail and decisions.
- `RosterSteps` for draft -> submitted -> approved -> published states.
- `Empty`, `Skeleton` and error banners for every async region.

Tables use `tp-table`: sticky headers, tabular numerals where useful, readable row labels, finite filters and explicit export permissions. Forms use `tp-field`, visible labels, disabled states and server error display.

## Shells and navigation

The customer shell lives in `AppShell`. Navigation must be permission-aware and reflect current product scope. Keep advanced or unfinished modules secondary.

Dedicated surfaces:

- `/kiosk`: full-screen device shell, no admin navigation.
- `/platform`: platform operator shell. Support access must be visibly distinct from customer login.
- `/billing`: commercial configuration shell only until entitlement and payment APIs exist.
- `/help`: help library and API reference discovery.

Kiosk and account/login routes must not inherit customer administration navigation.

## Page states

Every page and major panel should account for:

- Loading.
- Empty or not configured.
- Error and retry where practical.
- Partial data.
- Stale data.
- Synthetic or simulated data.
- Success after server acknowledgement.

Withhold misleading totals when required data is missing. Use "No verified data" or "Not configured" instead of zero.

## Core workflows

Roster Planner:

- Worker, date, time, coverage and conflicts must be easy to scan.
- Preserve keyboard/form editing alongside drag-and-drop.
- Distinguish draft, submitted, approved, published and reconciled.
- Hard conflicts block submit/publish and are explained in business language.

Attendance:

- Separate scheduled time, original punches, corrections, worked hours and approved payable hours.
- Corrections must preserve originals and require authorised approval.
- Open, late, absent, unrostered and pending states need clear labels.

Demand and reports:

- Show period, units, source, freshness and forecast basis.
- Distinguish supplied forecasts, Tempo model forecasts and manual adjustments.
- Label planned, estimated and confirmed figures.

Data and connections:

- CSV flow is upload -> map -> validate/preview -> confirm -> results.
- API flow is credential -> submit with idempotency -> receipt/status -> row errors.
- Connection health states include configured, syncing, stale, failed and verified.

## Responsive and kiosk rules

Verify desktop, narrow laptop, tablet and mobile layouts. Roster grids may scroll on desktop; mobile should offer readable list/timeline alternatives rather than a squeezed grid.

Kiosk:

- Large touch targets and readable text.
- Numeric PIN entry, masked identity and unmistakable confirmation.
- Safe-area support, portrait/landscape handling and virtual keyboard tolerance.
- Repeated taps and loading states must not duplicate punches.
- Online-only scope: show explicit outage message and supervisor route.
- Success appears only after server acknowledgement.

Future mobile delivery path: keep the browser kiosk app-like and packageable. A web wrapper is the smallest maintainable next step while Tempo remains online-only. A separate native client should wait for offline signed capture, device management or hardware integrations that the wrapper cannot satisfy.

For the first mobile packaging step, prefer a thin Capacitor-style web wrapper around the tested kiosk route. That keeps one React codebase, preserves the current online-only server acknowledgement model, and allows managed app distribution later without introducing a separate native feature backlog. Move to a native client only if offline signed capture, hardware NFC/biometric integration, managed device APIs, or background sync become accepted release requirements.

## Accessibility checklist

- Visible focus on every interactive control.
- Labels for inputs, filters, status and icon-only controls.
- Contrast meets WCAG AA for core text and controls.
- Status has non-colour cues.
- Dialogs/drawers trap focus and close with Escape.
- Tables have meaningful headers and captions where needed.
- Dynamic updates use `aria-live` only where useful.

## Extending unfinished areas

When preparing a shell, include:

- What is ready.
- What is not configured or coming later.
- The next API contract required.
- Links to the working adjacent route.

Do not expose many unfinished pages in primary navigation just because a shell exists. Add routes only when they reduce confusion or establish an approved product path.
