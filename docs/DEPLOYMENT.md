# Tempo — authoritative deployment record

This is the single place that says what is running. When it disagrees with `build-progress.md` (a historical ledger), this file wins.
Update it whenever the deployed stack changes. Last verified: **2 October 2026**, host `opc`, public name `https://tempo.ensemblesolutions.com.au/`.

## What is running

| Item | Value |
|---|---|
| Source revision of the running code | `51eeb42` on `build/tempo-standalone-gate1` (images built 2 Oct 2026 from a clean checkout of that commit, so uncommitted working-tree edits were not deployed). |
| Backend | container `tempo_backend`, image `tempo-api:local`, host port **8007** → 8000, runs as non-owner role `tempo_app` |
| Frontend | container `tempo_frontend`, host port **3007** → 80 |
| Database | container `tempo_postgres` (postgres:16), host `127.0.0.1:5439`, database `tempo`, roles `tempo_owner` (migrations) / `tempo_app` (runtime, no BYPASSRLS), volume `tempo_tempo_pgdata` |
| Migration head | **`a9b0c1d2e3f4`** (read from `alembic_version` in database `tempo`) |
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
No automated backups; no secret vault; database connection not TLS; one host, no failover; the capacity test is not part of CI; the demo tenant `ensemble_solutions` (synthetic data, account `tempo.admin`) is the only tenant.
