# Tempo standalone build — Gates 1–3 product workflow, login, and roadmap features

Standalone multi-tenant labour planning and attendance on PostgreSQL (row-level security), FastAPI + React.

## What's in it
- **Security foundation:** Tempo-issued sessions, username/password (Argon2id, lockout, TOTP for admins, invite-only), OIDC adapter, kiosk enrolment, platform-admin separation, tenant and **site-level** row security, append-only audit and a tenant audit log.
- **Workflow:** demand → roster versions (draft → approve → publish → reconcile) → attendance and supervised corrections → variance (estimate vs confirmed).
- **Latest additions:** CSV export, demand overrides (reason, expiry, second-person approval above ±25 %), drag-and-drop roster editing with undo, in-app notifications, Overlay-site roster hand-over, day-of-week forecast pattern, authenticator QR.

## Verification
- Backend: 303 tests on real PostgreSQL with the non-owner runtime role.
- Browser: 18 Playwright tests against a dev stack on its own database (`tempo_e2e`).
- Deployed to ports 3007/8007; migrations applied; sign-in over HTTPS checked.

## Known limits (see `docs/build-progress.md`)
No email/SMS delivery or self-service password reset; no real Deputy/UKG write client (hand-over is by file with operator attestation); IDs are not yet tenant-composite keys; OIDC untested against a real IdP; no secret vault.

## Review notes
Five migrations (`f6a7…` to `d0e1…`) are additive; the runtime role cannot DELETE override, notification or hand-over rows.
