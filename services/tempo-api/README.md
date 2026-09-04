# Tempo Optimisation Service — Phase 0

A FastAPI implementation of the contract foundation defined in
`Tempo_Prime_AI_Integration_Specification_v2.0.docx` (§18, Phase 0): *"Prime
can call a stubbed Tempo run end-to-end with governed evidence."*

This is not the WIEP MVP scaffold (`wiep-mvp.zip` at the repo root) — that
was a UI/heuristic proof of concept with no tenancy, versioning, or run
lifecycle. This service replaces it as the foundation going forward; the
scaffold is kept only as UI/interaction reference. See `docs/roadmap.md` at
the repo root for the full phase plan.

## What Phase 0 actually delivers

Real, tested code for the parts of the Integration Spec that every later
phase depends on:

| Spec section | Implemented as |
|---|---|
| §5 Identity, tenancy and entitlements | `app/schemas/tenancy.py`, `app/dependencies.py` — every request must carry an explicit, non-defaultable scope |
| §6 Canonical data model | `app/models/canonical.py` (entities), `app/schemas/envelope.py` (§6.2 ingestion envelope) |
| §7.3 Readiness API | `app/api/v1/readiness.py` |
| §8 Run contracts | `app/schemas/runs.py`, `app/api/v1/runs.py` |
| §10 Run orchestration and lifecycle | `app/core/lifecycle.py` — the state graph is transcribed from §10's table |
| §11 Explainability and governed evidence | `app/core/confidence.py`, the `Explanation` schema in `app/schemas/runs.py` |
| §13 Events | `app/core/events.py` — outbox-backed, in-process delivery for now |
| §14.2 Audit record | `app/core/audit.py` |
| §8.6 / Appendix B Error contract | `app/errors.py` |

What's **stubbed**, deliberately: the four run types
(`demand_forecast`, `labour_requirement`, `workforce_mix`, `named_roster`)
go through the real pipeline above but return deterministic placeholder
numbers, not real solver output — that's Phase A. Every other `run_type` in
Appendix C is a legal request that returns `TEMPO-RUN-004` rather than a
404, so Prime's tool schema doesn't need to change as later phases land.

## Known Phase 0 simplifications (tracked, not hidden)

- **Identity**: §5.3 specifies OIDC/OAuth2 JWTs between Prime, Tempo and
  Maestro. Standing up a real IdP is out of scope here — callers instead
  present an already-validated scope via an `X-Tempo-Context` header. This
  is a stand-in for a token verifier, not a security control, and must not
  reach a production/pilot environment (tracked as OD-01 in the spec).
- **Canonical ingestion**: there's no real Maestro connector yet (that's
  Phase B). The canonical tables in `app/models/canonical.py` exist so the
  readiness/run pipeline has something real to query; populate them via
  direct inserts or a small seed script during Phase 0 testing.
- **Idempotency store and event bus** are in-process (`app/core/idempotency.py`,
  `app/core/events.py`) — fine for one API replica, not for Phase F scale.
- **Database**: SQLite by default (`TEMPO_DATABASE_URL` env var to override).
  Production target is Oracle Autonomous Database per spec §17.1; swapping
  the URL is enough at this layer since there's no Oracle-specific SQL here,
  but this hasn't been validated against ADB.

## Run it

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Docs at `http://localhost:8000/docs`. Every request needs an
`X-Tempo-Context` header (see `tests/conftest.py::context_header` for the
shape) and run-creation calls need an `Idempotency-Key` header.

## Test it

```bash
pytest
```
