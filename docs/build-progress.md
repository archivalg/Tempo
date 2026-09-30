# Tempo build progress ledger

Branch: `build/tempo-standalone-gate1` (from main @ 03e4b58). Blueprint v1.1 (29 Sep 2026) was supplied inline;
`docs/Tempo_Product_Build_Blueprint.md` does not exist in the repo yet, so this ledger cites blueprint section numbers.

## Baseline (verified 2026-09-29)
- API tests: 187 passed on Python 3.12 (excl. `test_capacity.py`), ~7 min. System Python is 3.9; use `uv venv --python 3.12`.
- Running: `tempo_backend` :8007 and `tempo_frontend` :3007 containers (SQLite, X-Tempo-Context scaffold).
- Uncommitted user work on main: docker-compose, console Dockerfile/nginx, `randomUUID` fallback for plain HTTP.

## What works
Ten solvers; canonical models; Deputy/UKG/WMS connector code; action validate/approve/execute/reconcile; native roster
publish; PIN/NFC attendance; Alembic baseline; identity tables + AccessScope resolver (unit-tested, unwired); thin React console.

## Gap assessment (vs. blueprint gates)
| Gate | Gap | Status |
|---|---|---|
| 1 Identity | `get_request_context` trusts `X-Tempo-Context`; console stores claims in localStorage; `/setup` page; no OIDC, sessions, MFA, CSRF; AccessScope not wired | OPEN |
| 1 DB isolation | SQLite only; no VPD/RLS; ADR-0002 unsigned; no Prime stack comparison (needs repo/env access) | OPEN, blocked on owner |
| 2 Bootstrap | No `bootstrap_ensemble_demo`, no Makefile, no .env.example | OPEN |
| 3 UX | No design tokens, shell, Overview / Roster Planner / Attendance screens, Tempo logo assets (only `Tempo Traffic Light.png` present) | OPEN |
| 4 Cycle | No async worker/queue; fixed shift calendar; $40 fallback | OPEN |
| 6 Writeback | Vendor outcome always `unknown` | OPEN |
| 0 Ownership | Repo protection/licence not verifiable from here | OPEN, needs owner |

## Sequence
1. Wire a trusted principal resolver (server-side sessions/OIDC adapter behind an interface) into `get_request_context`; remove header trust; IDOR/forged-header tests.
2. Platform-admin bootstrap command; audit; kiosk enrolment.
3. `bootstrap_ensemble_demo` + Makefile + `.env.example`.
4. Design tokens + shell + three screens, browser-verified.
5. Async runs, roster edit/validate/approve/publish, attendance, variance report; browser e2e.

## First files to change
`services/tempo-api/app/dependencies.py`, `app/core/access_scope.py`, `app/config.py`, new `app/core/auth.py`,
`app/api/v1/auth.py`, `tests/test_forged_header.py`; console `src/api/client.ts`, `src/context/*`, `pages/ContextSetup.tsx`, `App.tsx`.

## Decisions needing owners (not blocking local work)
Trev's verified IdP subject/email; IdP choice; production DB vs Prime stack; DNS names; vendor sandboxes; pilot rules; RPO/RTO.
Local assumption meanwhile: pluggable OIDC verifier, local dev issuer only when `TEMPO_ENV=local`.

## Requirement ledger
| ID | Requirement | Status | Evidence |
|---|---|---|---|
| G0 | Baseline pinned, tests run | done | 187 passed, 3.12 |
| G1-1 | Remove caller-asserted identity | not started | — |
