# Tempo Console

A React + TypeScript single-page app for `services/tempo-api` — the "Real-Time
Operations Console" named in the Business Specification (§4, §8) as one of
the Consumption layer's surfaces (the others being Prime AI's agents and
"any authorised API client," both already served by the existing REST API).

This is the **first UI in the Tempo codebase**. Everything built before it
(Phases 0-F, per `docs/roadmap.md`) was the Optimisation Service's backend —
solvers, connectors, and the REST/action/onboarding API. This console is a
thin client over that API; it adds no new backend logic of its own beyond
two small additions the console needed and the backend gained honestly:

- `GET /v1/runs` and `GET /v1/actions` (cursor-paginated list endpoints) —
  the console's list views need something more than `GET /v1/runs/{id}`'s
  single-record lookup.
- `GET /v1/runs/{run_id}` now also returns `run_type` and `recommendation_id`
  on a completed run, so the console can offer "start an action from this
  run" without the caller having to keep the create-run response around.

A second round added the **Kiosk** and **Team attendance** pages once
`services/tempo-api` gained native capture (PIN/NFC clock-in,
`app/api/v1/attendance.py`) — no new backend endpoints needed this time,
native capture already shipped everything these two pages consume.

## What it covers

Per the Business Specification's UX roles table (§8), this v1 covers
**Operations Manager**, **Tenant Admin**, and (partially) **Executive** —
the roles whose stated needs ("Publish rosters, review AI recommendations,
manage performance" / "Manage hierarchies, rules, integrations, feature
access" / "Review network performance, labour cost, and risk") map onto
capability the backend already fully implements:

- **Dashboard** — data readiness by capability, and model monitoring
  (backtest error, solver-gap rate, confidence, version adoption) with an
  on-demand drift check.
- **Runs** — list/filter/paginate, create a run for any of the ten
  `run_type`s (one generic form — every run_type shares the same
  `RunRequest` shape per the Integration Spec), and a detail view showing
  the full explanation contract (baseline/proposed/delta/confidence/
  primary drivers/missing evidence) plus the raw result.
- **Actions** — §12's two-step contract end-to-end: validate a
  recommendation (impact summary + token), execute it (requires
  `labour.approve`), and reconcile an `unknown` outcome. The console does
  not hide that there's no real vendor writeback connector yet (Phase E's
  disclosed gap) — it shows `unknown` and the reconciliation flow exactly
  as the API reports them, never a fabricated "confirmed."
- **Onboarding** — the connector catalogue, and self-service registration
  of tenant scopes and connections (Phase F). A registered connection
  stays `pending_credentials` in the UI too, honestly, for the same reason
  it does in the API.
- **Kiosk** (Worker) — a PIN identifies the worker (no worker login exists
  — same disclosed stand-in as everything else here), then shows their
  upcoming/recent shifts and a Clock in/Clock out button reflecting their
  actual open-session state (`GET/POST /v1/attendance/*`). "Know shifts,
  clock in/out correctly" from §8's Worker row.
- **Team attendance** (Supervisor) — every attendance session at a site
  within a configurable window, with `matched_rostered_shift: false`
  entries surfaced as exceptions in their own callout, not just another
  table row. "Cover shifts, manage exceptions" from §8's Supervisor row —
  a starting point (no live alerting/push notification), not the full
  "respond to live alerts" half of that need.

**Not covered — deliberately out of scope for this pass**, because the
backend capability it would need doesn't exist yet (see
`services/tempo-api/README.md`'s "Known simplifications"):

- **Labour Provider role** — "manage supplied workers, certifications,
  shift assignments" needs a labour-hire-specific data model (which
  workers belong to which provider, a provider-facing scope) that neither
  the canonical model nor the console's tenant/site-scoped identity
  supports yet.
- **Run comparisons UI** — `POST /v1/run-comparisons` exists and is
  exercised by the backend test suite, but the console has no page for it
  yet; a small, natural follow-up.

## Identity — a disclosed stand-in, not a login

`services/tempo-api` has no identity provider (`app/dependencies.py`'s own
docstring: the `X-Tempo-Context` header is "a Phase 0 stand-in, not a
security control, and must not reach production"). The console's
`/setup` page mirrors that honestly instead of hiding it behind a fake
"Sign in" screen: it's a form for the same fields — tenant, sites,
customers, user, roles — stored in `localStorage`, not a credential
exchange. Switching roles there is how you test what each §5.2 permission
actually gates (e.g. `labour.approve` vs `labour.plan`, or
`labour.margin.read`).

## Known simplifications (tracked, not hidden)

- **No automated end-to-end test** — this was manually verified against a
  live `tempo-api` instance in a real browser (Chromium via Playwright,
  used only as a one-off manual check, not a checked-in dependency) before
  being called done. A Playwright test suite committed to the repo, run in
  CI against a live backend, is a natural next step, not yet built.
- **Pagination is "next page only," no "jump to page N"** — matches the
  backend's cursor-based pagination (§8.1) directly; there is no total
  count to build a page-number UI from.
- **CORS is wide-open for local dev** (`TEMPO_CONSOLE_CORS_ORIGINS`,
  default `http://localhost:5173`) — a real deployment sets this to the
  console's actual origin(s), same class of dev-only default as
  `action_token_secret`.
- **No design system** — plain hand-written CSS (`src/index.css`), no
  component library. Fine for an internal ops console; a customer-facing
  surface would want one.
- **Kiosk has no real device/session identity** — it's just another page
  in the same console session; a real kiosk deployment would run it as a
  locked-down, tenant/site-pinned browser session on shared hardware, not
  a page a signed-in ops user happens to click into.
- **Team attendance has no live/push updates** — it's "Refresh" on demand,
  not a live feed; the "respond to live alerts" half of the Supervisor
  need isn't built (same root gap as the backend's own disclosed "no
  background scheduler").

## Run it

Two processes, from the repo root:

```bash
# Terminal 1 — the API (see services/tempo-api/README.md for details)
cd services/tempo-api
uvicorn app.main:app --reload

# Terminal 2 — the console
cd services/tempo-console
npm install
npm run dev
```

Open `http://localhost:5173`. `.env.development` points the console at
`http://localhost:8000/v1` by default (`VITE_API_BASE_URL` to override).

The API has no seed data of its own — see
`services/tempo-api/tests/factories.py` for a worked example, or use the
console's own Onboarding page to register a tenant scope and connection
(registration only; it doesn't ingest data — see the gap noted above).

## Test it

```bash
npm run test    # vitest — API client and component-level tests
npm run build   # tsc -b && vite build — typechecks and production-builds
npm run lint    # oxlint
```
