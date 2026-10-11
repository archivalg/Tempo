# Tempo — authoritative deployment record

This is the single place that says what is running. When it disagrees with `build-progress.md` (a historical ledger), this file wins.
Update it whenever the deployed stack changes. Last verified: **11 October 2026**, host `opc`, public name `https://tempo.ensemblesolutions.com.au/`.
For what the deployed revision actually *does* (capability by capability, with evidence), see [`PRODUCT-STATE.md`](PRODUCT-STATE.md).

## What is running

| Item | Value |
|---|---|
| Source revision of the running code | `6723cb0` on `build/order-driven-planning` (images built 11 Oct 2026 from a clean checkout of that commit; working tree was clean at build time). |
| Backend | container `tempo_backend`, image `tempo-api:local`, host port **8007** → 8000, runs as non-owner role `tempo_app` |
| Frontend | container `tempo_frontend`, host port **3007** → 80 |
| Database | container `tempo_postgres` (postgres:16), host `127.0.0.1:5439`, database `tempo`, roles `tempo_owner` (migrations) / `tempo_app` (runtime, no BYPASSRLS), volume `tempo_tempo_pgdata` |
| Migration head | **`d8e9f0a1b2c3`** (read from `alembic_version` in database `tempo`) |
| Migration job | `tempo_migrate` (one-shot, owner role, `alembic upgrade head`) |
| Redis | not used (6386 reserved) |
| Dev identity picker | **OFF** in the deployed stack (`TEMPO_DEV_IDP_ENABLED=false`); password sign-in only |
| Gateway | `central_nginx` (separate repo `Ensemble_NGNIX`): HTTP→HTTPS redirect, TLS on the Tempo hostname, upstreams `tempo_backend:8000` and `tempo_frontend:80` |

## Not yet deployed
Nothing committed. **Uncommitted UI-pass edits** (design tokens, Help/Billing/Platform shells, restyled pages; see `docs/ui-route-checklist.md`) exist in the working tree and are deliberately not in the running build.

## How to deploy (no data loss)
```bash
cd /home/opc/tempo
docker compose build tempo_migrate tempo_frontend      # backend and migrate share image tempo-api:local
docker compose up -d tempo_migrate tempo_backend tempo_frontend
docker logs tempo_migrate | grep -E "Running upgrade|ERROR"
TEMPO_CREDENTIALS_FILE=~/.config/tempo-secrets/tempo-admin-login.txt scripts/smoke.sh
```
Never use `docker compose down --volumes`. Never point the demo reset or browser tests at database `tempo`.

## Separate throw-away databases on the same server
| Database | Purpose | May be wiped |
|---|---|---|
| `tempo` | live | **No** |
| `tempo_test` | pytest (truncated at start of each run) | Yes |
| `tempo_e2e` | Playwright + the dev stack (`scripts/e2e.sh`, `scripts/dev-up.sh`) | Yes |
The demo reset (`bootstrap-ensemble-demo --reset`) now **refuses** any database other than `tempo_e2e` / `tempo_test` unless `TEMPO_DEMO_RESET_DB=<name>` is set on purpose (tested).

## Verification record
- **11 Oct 2026 (`6723cb0`, order-driven labour planning — order-driven demand, personal/day rates,
  indirect coverage, dependencies, equipment, congestion/staging, grade/award costing, committed-vs-
  fulfilled backlog, XLSX workbook import)**: ten additive migrations applied cleanly,
  `f1a2b3c4d5e6` → `d8e9f0a1b2c3` (new tables/columns only; every migration's `downgrade()` reverses
  it, `upgrade()` never drops or alters existing data — verified by inspection before deploying).
  Pre-deploy dump `~/tempo-backups/tempo-pre-orderdriven-20261010-235549.dump` (verified readable,
  699 TOC entries); rollback images `tempo-api:rollback-20261010-235549` and
  `tempo-tempo_frontend:rollback-20261010-235549` (the prior running revision, `51eeb42` / migration
  head `a9b0c1d2e3f4` — rollback: retag both images to `:local`/`:latest`, `docker compose up -d
  tempo_backend tempo_frontend`; no `alembic downgrade` needed since the new schema is additive and
  ignored by the older code). Backend suite 520 passed; browser e2e 3/3 passed (upload/run/results,
  a constrained run's explained shortfall, and XLSX upload + explicit completion through a real
  authenticated session). Smoke test passed (full list below). Deployed-revision checks run directly
  against the live hostname: container health (`tempo_backend` healthy, `tempo_frontend` and
  `tempo_postgres` up), login (via smoke), workbook upload/preview (`POST /v1/imports/xlsx/inspect`
  against a real fixture, sheet recognised, guidance/example rows correctly excluded from the row
  count), order-fulfillment run creation/results (a draft run against a clearly-labelled verification
  order `DEPLOY-VERIFY-1` on site `mel_dc_01`, process `deploy_verify`, completed with a disclosed
  warning — no shift templates configured for that site, handled as a normal `completed_with_warnings`
  outcome, not an error), and commitment release vs actual completion (a committed run brought
  `committed_units` to 20/`fulfilled_units` to 0; releasing that run's commitment returned
  `committed_units` to 0 while `fulfilled_units` stayed 0; an explicit completion call then moved
  `fulfilled_units` to 5 while `committed_units` stayed 0 throughout — the planning/actual separation
  holds on the live database, not only in tests). The verification process template/steps/order
  (`deploy_verify` / `DEPLOY-VERIFY-1`) were left in place afterwards as clearly-labelled evidence,
  consistent with this demo tenant's existing synthetic data, rather than attempting a partial cleanup
  with no delete endpoint to match. **Source-workbook compatibility with Arch's actual v1/v2 files
  remains explicitly unverified** — see `docs/order-driven-planning.md`'s "Sixth pass" section; this
  deployment is fixture-tested import support, not confirmed compatibility with the real files, which
  have not been supplied to this programme at any point.
- Smoke test against the public hostname (`scripts/smoke.sh`): readiness, console, anonymous refusal, password sign-in, and read-only calls for overview, demand, rosters, roster, live attendance, timesheets, variance, notifications, data status, setup checklist, data contracts; sign-out. Last run: **passed**, 1 Oct 2026.
- 4 Oct 2026 (`c3e096e`, email-code two-step verification): sign-in/enrolment by emailed 6-digit code for web, mobile and kiosk manager exit; additive migration `a9b0c1d2e3f4` (`tempo_user.email_mfa_enabled_at`, `email_otp`); pre-deploy dump `~/tempo-backups/tempo-pre-emailmfa-20261004-092502.dump`, rollback images `...:rollback-20261004-092502` (older code ignores the new column/table); backend suite 419 passed (capacity tests excluded); smoke passed. SMTP account for the platform was loaded by an operator on 4 Oct 2026 and a platform-admin invitation email was accepted by the mail server and received; email codes themselves have not been exercised by a person against the live mailbox yet.
- 4 Oct 2026 (`1140f43`, platform SMTP): Platform console → Email, encrypted SMTP account, test connection / test email, message log without bodies, best-effort invitation emails; additive migration `f8a9b0c1d2e3` (`smtp_config`, `email_message` with row security); pre-deploy dump `~/tempo-backups/tempo-pre-smtp-20261004-073058.dump`, rollback images `tempo-api:rollback-20261004-073058` and `tempo-tempo_frontend:rollback-20261004-073058` (re-tag to `:local`/`:latest` and `docker compose up -d`; the new tables are additive and unused by older code); backend suite 413 passed (capacity tests excluded, known load-sensitive); smoke passed. **No SMTP account is stored yet** in this database: it is loaded by an operator with `docker exec -i tempo_backend python -m app.cli set-smtp ... --password-stdin`, or typed into the console. No email has been sent from this system; real delivery is unverified until then.
- 4 Oct 2026 (`baa6f3d`): Team & skills page rebuilt; web page for team members at `/my`; platform admins can invite further administrators into a tenant (`POST /v1/platform/tenants/{id}/admins`); no migration; ports/containers unchanged (8007, 3007, 5439); rollback images `*:rollback-pre-teamweb`; targeted API tests (51) and browser specs passed; smoke passed.
- 4 Oct 2026 (`08ed376`, mobile foundation): backend + web for the employee app and kiosk; additive migration `e7f8a9b0c1d2`; **containers and ports checked before and after: `tempo_backend` 8007→8000, `tempo_frontend` 3007→80, `tempo_postgres` 127.0.0.1:5439; no other service touched.** Pre-deploy dump `~/tempo-backups/tempo-pre-mobile-*.dump`; rollback images tagged `tempo-api:rollback-pre-mobile` and `tempo-tempo_frontend:rollback-pre-mobile` (rollback: retag them `:local`/`:latest`, then `docker compose -p tempo up -d tempo_backend tempo_frontend`; the schema change is additive and can stay). API suite 408 passed; smoke passed. Notifications are OFF on this deployment (`TEMPO_PUSH_PROVIDER=disabled`, `TEMPO_JOBS_ENABLED=false`) until push credentials exist. The mobile app itself is not deployed anywhere (no builds exist).
- 3 Oct 2026 (`51eeb42`, third deploy): support sessions, guided setup wizard (migration `d6e7f8a9b0c1`), help library, public API documentation at `/v1/api/docs` and `/v1/api/openapi.json`, badge/active/skills editing. **Closes an information leak:** the framework's `/docs`, `/redoc` and `/openapi.json` had been publicly listing every internal route; all three now return 404. Pre-deploy dump `~/tempo-backups/tempo-pre-support-*.dump`; API suite 380 passed + 1 timing test (`test_capacity`) that failed under full-suite load and passes alone; browser suite 26 passed + 2 specs that failed in the full run and passed when rerun in sequence (one 4-minute timeout in password-login, not reproduced; one caused by a test that changed a seeded badge number, fixed). Smoke passed. The compose recreate of the backend briefly left a container named `<id>_tempo_backend`; it was renamed to `tempo_backend`.
- 3 Oct 2026 (`d977455`): platform operator console at `/platform`; platform routes accept the console cookie session with CSRF (bearer still works); no migration; pre-deploy dump `~/tempo-backups/tempo-pre-platform-*.dump`; auth/platform/subscription tests 66 passed; smoke passed. First platform admin (`tbarwise@ensemblesolutions.com.au`) created on the live database with a one-time invitation (not yet used at time of writing); the invitation link is in `~/.config/tempo-secrets/platform-admin-invite.txt` (mode 600, expires 72 h after creation).
- 2 Oct 2026 (second deploy, `0dc0200`): M3 shift definitions + availability + drill-through, M1 sites/customers/availability/rates import, M6 plans/manual subscriptions/allowance; migration `c5d6e7f8a9b0`; pre-deploy dump `~/tempo-backups/tempo-pre-m3m1m6-*.dump`; API suite 369 passed (one time-of-day-dependent test fixed); smoke passed incl. billing/plan and availability. Built from a clean checkout again.
- 2 Oct 2026 (first deploy): M2 (internal T&A, kiosk breaks, site geofence/location) and M3 first slice (roster locking, planning rules) deployed; pre-deploy dump `~/tempo-backups/tempo-pre-m2m3-*.dump`; migrations `f2a3b4c5d6e7`, `a3b4c5d6e7f8`, `b4c5d6e7f8a9` applied cleanly; smoke test passed (now also checks attendance policy, geofence, daily list, planning rules). API suite 358 passed. Not yet run in GitHub CI.
- API suite (real PostgreSQL, non-owner role): 325 passed on 1 Oct 2026 (run on this host; **not yet run in GitHub CI**).
- Browser suite (dev stack on `tempo_e2e`): 21 passed on 1 Oct 2026 (**not yet run in GitHub CI**).
- Backup/restore drill: one manual `pg_dump`/`pg_restore` of `tempo` into a scratch database on 1 Oct 2026; row counts matched. No schedule, off-host copy or timed recovery yet.

## Known operational gaps
No automated backups; no secret vault; database connection not TLS; one host, no failover; the capacity test is not part of CI; the demo tenant `ensemble_solutions` (synthetic data, account `tempo.admin`) is the only tenant. Order-driven planning (`6723cb0`): neither committing a run nor releasing a commitment nor confirming order completion has console UI yet — these are API-only (`input.committed`, `POST /v1/runs/{id}/release-commitment`, `POST /v1/orders/{id}/complete`); XLSX workbook upload is also API-only (`POST /v1/imports/xlsx/inspect`/`stage`), and its compatibility with Arch's actual v1/v2 source files is unverified (see `docs/order-driven-planning.md`).

## Frontend release: landing pages and UI refresh

- `3f231a7`: `/landing` and `/landing2` public pages. `8c55410`: UI design-system refresh, Billing, Help and Platform Admin pages. Deployed 2026-10-05, frontend only (no backend or database change; backend remains `c3e096e`, migration head `a9b0c1d2e3f4`).
- Rollback image: `tempo-tempo_frontend:rollback-20261005-013356`. Smoke test passed; `/landing`, `/landing2`, `/login`, `/billing`, `/help` return 200.
- `ee48fed` and later add only docs, AGENTS.md and a patch file, so no redeploy is needed for them.
