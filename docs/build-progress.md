# Tempo build progress ledger

Branch `build/tempo-standalone-gate1`. Spec: [`Tempo_Product_Build_Blueprint.md`](Tempo_Product_Build_Blueprint.md) v1.2 (30 Sep 2026).
**No gate is complete.** Status values: `verified` (demonstrated by executed tests/running system as noted), `partial`, `open`, `blocked` (needs named owner).

## Decisions
- **PostgreSQL 16 + RLS** approved 30 Sep 2026 — [ADR-0011](adr/0011-postgresql-rls.md) supersedes Oracle ADR-0002/0010. Own DB, own credentials.
- Stack alignment checked read-only against the sibling Ensemble products on this host: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PyJWT, React 19/TypeScript. No Prime connector/runtime dependency exists or is planned.
- RPO 15 min / RTO 4 h are **provisional planning assumptions** until approved and restore-tested.
- Production IdP: **open** (ADR-0001). Adapter is provider-agnostic; local dev IdP is env-restricted and labelled non-production.

## Environment (this host)
- `tempo_postgres` (postgres:16, 127.0.0.1:5439, roles `tempo_owner` migrations / `tempo_app` runtime, dbs `tempo`, `tempo_test`) defined in `docker-compose.yml` with `docker/postgres/01-roles.sh`.
- Generated secrets live in gitignored `/home/opc/tempo/.env` (mode 600, owner `opc`). Rotation: regenerate values, `docker compose up -d`, re-run role script (`ALTER ROLE ... PASSWORD`), invalidate sessions by changing `TEMPO_SESSION_SIGNING_KEY`. Not yet automated. Dedicated `.env.development.local`/`.env.uat` outside the repo: **open**.
- **Deployed (30 Sep 2026, commit 4f7ae61):** `tempo_postgres` 127.0.0.1:5439 (volume `tempo_tempo_pgdata` preserved; backup `~/tempo-backups/`), one-shot `tempo_migrate`, `tempo_backend` 8007 (image `tempo-api:local`, non-owner `tempo_app`, `/readyz` ok, dev IdP OFF), `tempo_frontend` 3007. Gateway unchanged (it already targets `tempo_backend:8000` / `tempo_frontend:80`; only `/readyz` is not in its route regex). The public hostname shows the sign-in page with *no identity provider configured* — nobody can sign in there until the login milestone. Legacy SQLite volume `tempo_tempo_data` retained, unused.
- Local dev/verification stack (dev IdP ON, loopback only): API 127.0.0.1:8017, console 127.0.0.1:5174, driven by local Playwright Chromium (`/tmp/claude-1000/dev-up.sh`).
- Python 3.12 venv: `/tmp/claude-1000/v312` (`uv venv`), system Python untouched.

## Verification run (2026-09-30, real PostgreSQL, non-owner runtime role)
`pytest --ignore=tests/test_capacity.py` → **244 passed** (baseline before Gate 1: 187 on SQLite).

## Build priority (revised 30 Sep 2026, owner instruction)
Product workflow first; the full login / RBAC / security-hardening milestone is **deferred** until the workflow works, and will add a username+password experience. Tenant-aware data model and RLS continue as we build. Until then: dev IdP is local-only, never on the public hostname.

Sequence:
1. Professional Overview / Roster Planner / Live Operations on Ensemble sample data — **built, browser-verified locally** (see Screens).
2. Demand → roster: Demand workspace; roster **versions** (draft → edit → validate → submit → approve → publish → reconcile); rest/availability/cert rules in the solver.
3. Approvals inbox; attendance timesheets + corrections (never overwrite the original punch).
4. Variance: planned vs attended vs payable hours/cost, adherence, forecast accuracy — labelled estimate vs confirmed.
5. Browser e2e of the whole flow (Playwright) + screenshots.
6. Then: login milestone (username/password), full RBAC matrix, site/customer RLS, service clients, then remaining modules.

## Gate 1 — safe standalone foundation
| ID | Requirement (Blueprint) | Status | Evidence / gap |
|---|---|---|---|
| G1-01 | Remove caller-asserted identity (§5.1) | **partial** | `X-Tempo-Context` no longer read anywhere; `tests/test_identity_boundary.py` (forged header ignored/401, tenant selector checked vs memberships, tampered/unsigned/expired tokens, revocation, token_version, grant removal, refresh replay, CSRF, prod-config refusal). **Gap:** console still sends the old header and `/setup`; needs migration (deferred to the login milestone). |
| G1-02 | OIDC adapter + sessions (§5.1) | **partial** | Code: `core/oidc.py` (PKCE, JWKS rotation, iss/aud/exp/nonce), `core/auth.py`, `api/v1/auth.py`. Rotating refresh + family revocation + HttpOnly/CSRF tested with the **dev IdP only**. **Not verified against any real IdP** (blocked: IdP choice). Access-token revocation is DB-checked per request. |
| G1-03 | MFA for admins (§5.1) | **partial** | Admin role without MFA loses admin permissions; platform routes require MFA + 30-min step-up. MFA assertion comes from IdP `amr`; untested with a real IdP. |
| G1-04 | AccessScope single resolver (§5.2) | **partial** | Principal→`AccessScope` used by `/me/access`; handlers use the resolved `RequestContext` (roles/grants from Tempo tables). Legacy per-handler `context.has_permission` calls remain — not yet a single decorator; permission catalogue (`platform.*`, `site.*`, `device.*` …) **not yet implemented** (still 8 legacy codes). |
| G1-05 | Scope enforcement on list/detail/write/count/export/monitoring (§5.2) | **partial** | Fixed real leaks found by the matrix: runs (detail/list/cancel/compare) ignored site scope & labour.read; actions, connections, tenant-scopes, provider workers, ingestion (empty-grant bypass). `tests/test_access_matrix.py` (15 tests): all-routes-anonymous=401 from OpenAPI, tenant B × 17 object routes, other-site user, customer-only user, role-lacks-permission ×7, kiosk token & console token cross-use. **Gaps:** matrix covers implemented routes only; exports, reports, background-worker revalidation not built yet; counts/aggregates n/a until reports exist. |
| G1-06 | PostgreSQL RLS fail-closed, separate roles (§5.3) | **verified (tenant level)** | `tests/test_rls.py` (10): runtime role non-owner/no bypass/can't alter RLS; every `tenant_id` table has RLS+policy (build fails otherwise); no-context ⇒ 0 rows & no writes; under-filtered SQL & cross-join see one tenant; cross-tenant write & tenant-move rejected; pooled-connection reuse; tenant switching; audit append-only; identity tables invisible outside auth phase. **Gaps:** site/customer/provider RLS not done; legacy global PKs (`worker_id`); no TLS/vault; worker/background jobs use `tenant_session` but no queue yet. |
| G1-07 | Platform admin bootstrap (§5.2) | **verified (dev IdP)** | `python -m app.cli bootstrap-platform-admin --subject|--email --operator --confirm-verified-identity`; refuses when an admin exists; email invitation links only on that verified address; no password; audited (`tests/test_platform.py`, 9). **Blocked:** the real verified identity for Trev must be supplied by him (nothing guessed or hard-coded). Second-admin recovery API implemented (`POST /v1/platform/admins`). |
| G1-08 | Platform separation, support grants, kill switch (§3.4, §7) | **partial** | Separate `/v1/platform/*` principal, no tenant-data route, tenant create/suspend, support grants (≤8 h, reason, distinct approver when >1 admin, audited), global audit, tenant writeback switch default OFF. Suspension blocks users and kiosks (tested). **Gap:** support-grant *use* path (impersonation-free diagnostics) and global kill switch check at execute are not wired. |
| G1-09 | Kiosk enrolment & security (§3.3) | **verified (API)** | Enrolled device principal (tenant+sites from record), one-time 15-min code, HMAC-stored device secret, Argon2id PINs, worker# + PIN, per-worker & per-device lockout + audit, uniform failure, tenant/site tamper fails, disable/suspend stops device (`tests/test_kiosk.py`, 11). **Gaps:** offline punches undefined/untested; NFC tag cloning risk unmitigated; no browser kiosk UI on new flow yet. |
| G1-10 | Audit (§5.3) | **partial** | Security audit events for login/deny/kiosk/platform/device; runtime role cannot UPDATE/DELETE. No audit-retrieval API for tenants yet. |
| G1-11 | App/API origins, cookies, CORS (§5.1) | **partial** | Credentialed CORS with explicit origins/headers, SameSite=Lax HttpOnly cookies, CSRF. Separate `app.*`/`api.*` hostnames **blocked** (DNS). |
| G1-12 | Config safety (§8) | **partial** | `validate_settings` rejects insecure defaults in uat/production (tested). `.env.example` (root + API). Vault/secret store **open**. |
| G1-13 | Migrations on PostgreSQL | **verified** | Alembic 0001–0003 apply on clean PG; upgrade→downgrade base→upgrade round-trip test. |

## Known unsafe / incomplete right now
- The **console (port 3007) has not been migrated**: it still uses the removed header + `/setup`. Old backend container still runs the SQLite scaffold — do not expose either outside the box.
- `Worker.worker_id` etc. are globally unique PKs (cross-tenant collision hazard). Composite-key migration required.
- No real IdP, no vault, no TLS-to-DB, no backup/restore evidence (Gate 5 items).
- Test-suite runtime ~10 min (Argon2 cost + FK fixtures); acceptable, to be tuned.

## Next (in order)
1. Console: real login page (dev IdP banner), cookie session + CSRF client, `/me/access`-driven nav; delete `/setup` and header code.
2. `make` targets + `bootstrap_ensemble_demo` (idempotent, synthetic-labelled) + browser check on real seeded data.
3. Design tokens/components + Overview, Roster Planner, Attendance screens; screenshots.
4. Permission catalogue + site/customer RLS; service-client principal; async run worker.
