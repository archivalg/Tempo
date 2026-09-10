# Phase 3 Status: Integration Service and Optional Maestro Connectivity

## What's built (working evidence)

- **INT-01 (adapter boundary)**: documented, not mechanically extracted
  into a separate deployable — there's no deployment target to extract
  into yet (ADR-0004 pending), and `app.maestro` already has zero
  vendor-name leakage into `app.solvers` (verified by grep: no
  `deputy`/`ukg`/`kronos` anywhere in `app/solvers/*.py`). One nuance found
  during this audit and disclosed rather than hidden:
  `app/maestro/native_writeback.py` imports `app.solvers.shifts.SHIFT_CALENDAR`
  — `app/maestro/base.py`'s docstring claims "zero imports from
  app.solvers," which is true of `base.py` itself but not of the
  `app.maestro` package as a whole. This is a Tempo-owned governed
  constant (the shift calendar), not a vendor leak — reusing it avoids a
  second, driftable copy of the same shift definitions — but it means the
  package-level isolation claim was narrower than it read. ADR-0009
  already recommends staying with a direct Tempo connector rather than a
  separate Maestro service for the pilot, so this doesn't block anything
  today; it matters once/if `app.maestro` is actually extracted, since
  that extraction would need `app.solvers.shifts` (or just
  `SHIFT_CALENDAR`) to come along or be duplicated.
- **INT-02 (versioned canonical ingestion contract)**: `POST /v1/ingestion/events`
  (`app/api/v1/ingestion.py`) — genuinely new. `app.core.ingestion.apply_canonical_envelope`
  (§6.2's idempotent-upsert-or-dead-letter core) existed since Phase B but
  was only ever called from inside a connector's own Python code; despite
  `CanonicalEnvelope`'s own docstring claiming a `/v1/canonical/ingest`
  endpoint existed "to prove the downstream pipeline," no such endpoint
  has ever existed in this codebase — corrected in that docstring now that
  a real one does. The new endpoint validates tenant binding (the
  envelope's claimed `tenant_id` must match the caller's authenticated
  tenant) and contract version (`schema_version`) before touching the
  canonical store, gated on `labour.writeback` (§5.2's "Restricted
  integration role") since Phase 1's service-credential issuance isn't
  wired to real authentication yet. Proven idempotent: resubmitting the
  same record upserts the same row, never a duplicate.
- **INT-03/INT-04 (credential lifecycle)**: `app/maestro/credentials.py`'s
  `CredentialStore` + `ConnectorCredentialReference` (new table) +
  five new endpoints (`.../credentials`, `.../test`, `.../activate`,
  `.../suspend`, `.../revoke`) give `MaestroConnection.status` a real
  lifecycle (`pending_credentials` → `credentials_stored` → `active`,
  with `suspended`/`revoked` reachable from `active`) — replacing a
  `status` field that, before this pass, could only ever hold
  `pending_credentials` forever, plus a declared-but-dead `disabled` value
  nothing ever set. Honestly scoped: no real vendor endpoint exists to
  test credentials against, so `.../test` reports only "a credential
  reference is present," never a fabricated live handshake.
- **INT-11 (connector health)**: `GET /v1/connections/{id}/health` —
  checkpoints, last successful sync, lag, dead-letter counts (resolved vs.
  total). Honestly empty for a connection that's never synced, since none
  ever has (INT-05/INT-06 below).
- **INT-12 (no vendor fields in solver interfaces)**: audited, confirmed
  clean by grep — see INT-01's note above for the one adjacent nuance
  found (a Tempo-owned constant, not a vendor field).

## What's blocked on real infrastructure (INT-05, INT-06)

Both require a live vendor sandbox this environment cannot reach:
certifying the WMS read connector and either Deputy or UKG against real
API behaviour (pagination quirks, real field names, rate-limit headers).
`app/maestro/wms/client.py`, `app/maestro/deputy/client.py`, and the UKG
clients all exist and are unit-tested against their documented API shapes,
but — per this codebase's own long-standing disclosure — are "unverified
against a live tenant." Nothing new to add here beyond what was already
disclosed; ADR-0005 already flags this as the decision (which vendor) that
unblocks scheduling real certification work, once a sandbox exists.

## Test evidence

New this phase: `tests/test_connection_lifecycle.py` (6),
`tests/test_connection_health.py` (3), `tests/test_ingestion_endpoint.py`
(7) — 16 new tests. Full backend suite: **190 passed** (174 carried over
from Phase 2 + 16 new), no console changes this phase.
