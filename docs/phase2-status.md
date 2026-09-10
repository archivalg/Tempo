# Phase 2 Status: Production Data Platform

## What's built (working evidence)

- **DAT-02 (Alembic migrations)**: `alembic/` initialised, wired to
  `app.db.Base.metadata` and `app.config.settings.database_url` (env.py
  respects an explicitly-set URL rather than clobbering it — a real bug
  caught by the migration test itself failing on first run, fixed before
  being called done). Two migrations: a baseline covering every table as
  of this sprint, and one capturing DAT-06's snapshot-linkage schema
  change. `tests/test_migrations.py` proves upgrade head and downgrade
  base both work cleanly against a throwaway SQLite file.
- **DAT-03 (schema separation)**: designed, not mechanically implemented
  — SQLite has no real multi-schema support to implement or test it
  against. `docs/schema-separation-design.md` categorises every table into
  `tempo_core` vs `tempo_integration` and specifies exactly what Phase 2's
  real implementation should do once ADR-0002 lands.
- **DAT-04 (pooling/retry/timeout)**: `app/db.py::build_engine_kwargs` — a
  pure function, tested directly (no real database needed, since
  `create_engine` never connects eagerly) — applies pool size/overflow/
  timeout/recycle for a non-SQLite URL, correctly omits them for SQLite
  (whose default pool would reject them).
- **DAT-05 (JSON-embedded scope promoted to indexed columns)**: new
  `OptimisationRunSite`/`OptimisationRunCustomer` tables (a run's scope is
  genuinely a list, so a join table, not a single column) and a real
  `ActionRequest.site_id` column (genuinely single-valued). Both populated
  at creation, both tested.
- **DAT-06 (immutable snapshot linkage)**: new `OptimisationSnapshot`
  table — a real manifest (content hash, policy/model version, source
  watermarks), not just the bare generated ID string that existed before
  this sprint. `Recommendation.snapshot_id` and `ActionRequest.snapshot_id`
  both populated so either traces directly to its snapshot without a join.
  Disclosed limitation in the model's own docstring: `content_hash` covers
  the *requested* `RunRequest` parameters, not the full mutable canonical
  database's content at that instant — a true point-in-time data snapshot
  needs a temporal/versioned canonical model this pass doesn't build.
- **DAT-07 (retention policy)**: `docs/data-retention-policy.md` — windows
  per data class, explicitly marked draft pending real legal/customer
  retention requirements; no enforcement job exists yet (needs Phase 4).

## What's blocked on real infrastructure (DAT-01, DAT-08, DAT-09, DAT-10)

- **DAT-01** (Oracle driver + mapping validation): needs a real Oracle
  Autonomous Database and driver choice (ADR-0002). Nothing in this
  sandbox can install/validate against Oracle — no such instance exists
  reachable from here. What *is* checkable without one (SQLAlchemy dialect
  portability, avoiding SQLite-specific column types) was already true
  going in; this pass didn't introduce anything Oracle-incompatible
  (plain `String`/`DateTime(timezone=True)`/`JSON` throughout, same
  convention every existing table already used).
- **DAT-08** (encryption at rest/in transit, lower-environment masking):
  encryption at rest is an Oracle/OCI storage-layer configuration, not
  application code; in-transit is a connection-string/TLS-cert concern at
  deployment time. Lower-environment masking of worker PII needs actual
  lower environments to exist first (Phase 8) — `docs/environment-access-matrix.md`
  already specifies the target ("masked production-like data... never
  unmasked worker PII" outside production) but nothing enforces it yet.
- **DAT-09** (backup, point-in-time recovery, restoration runbook): needs
  a real Oracle/OCI environment to configure and *exercise* — a runbook
  written against infrastructure that doesn't exist would be unverified
  prose, not evidence. `docs/pilot-charter.md`'s NFR table already carries
  the target RPO/RTO (15 min / 4 hr, from the spec's own §15) this would
  be built and tested against.
- **DAT-10** (data contracts / migration compatibility rules for connector
  releases): depends on INT-02's canonical ingestion contract (Phase 3),
  not yet built — nothing to publish compatibility rules for yet.

None of these four are silently skipped — each is blocked by a named ADR
or a later phase's own prerequisite, not by oversight.

## Test evidence

New this phase: `tests/test_migrations.py` (2), `tests/test_scope_indexing.py`
(2), `tests/test_snapshot_linkage.py` (3), `tests/test_db_engine_config.py`
(3) — 10 new tests. Full backend suite: **174 passed** (164 baseline
carried over from the mobilisation sprint + 10 new), no console changes
this phase.
