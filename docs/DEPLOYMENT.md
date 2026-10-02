# Tempo — authoritative deployment record

This is the single place that says what is running. When it disagrees with `build-progress.md` (a historical ledger), this file wins.
Update it whenever the deployed stack changes. Last verified: **2 October 2026**, host `opc`, public name `https://tempo.ensemblesolutions.com.au/`.

## What is running

| Item | Value |
|---|---|
| Source revision of the running code | `29303db` on `build/tempo-standalone-gate1` (images built 2 Oct 2026 from a clean checkout of that commit, so uncommitted working-tree edits were not deployed). |
| Backend | container `tempo_backend`, image `tempo-api:local`, host port **8007** → 8000, runs as non-owner role `tempo_app` |
| Frontend | container `tempo_frontend`, host port **3007** → 80 |
| Database | container `tempo_postgres` (postgres:16), host `127.0.0.1:5439`, database `tempo`, roles `tempo_owner` (migrations) / `tempo_app` (runtime, no BYPASSRLS), volume `tempo_tempo_pgdata` |
| Migration head | **`b4c5d6e7f8a9`** (read from `alembic_version` in database `tempo`) |
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
- 2 Oct 2026: M2 (internal T&A, kiosk breaks, site geofence/location) and M3 first slice (roster locking, planning rules) deployed; pre-deploy dump `~/tempo-backups/tempo-pre-m2m3-*.dump`; migrations `f2a3b4c5d6e7`, `a3b4c5d6e7f8`, `b4c5d6e7f8a9` applied cleanly; smoke test passed (now also checks attendance policy, geofence, daily list, planning rules). API suite 358 passed. Not yet run in GitHub CI.
- API suite (real PostgreSQL, non-owner role): 325 passed on 1 Oct 2026 (run on this host; **not yet run in GitHub CI**).
- Browser suite (dev stack on `tempo_e2e`): 21 passed on 1 Oct 2026 (**not yet run in GitHub CI**).
- Backup/restore drill: one manual `pg_dump`/`pg_restore` of `tempo` into a scratch database on 1 Oct 2026; row counts matched. No schedule, off-host copy or timed recovery yet.

## Known operational gaps
No automated backups; no secret vault; database connection not TLS; one host, no failover; the capacity test is not part of CI; the demo tenant `ensemble_solutions` (synthetic data, account `tempo.admin`) is the only tenant.
