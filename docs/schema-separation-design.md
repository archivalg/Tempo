# Schema Separation Design (DAT-03)

DAT-03: "Separate Tempo canonical, run and audit data from connector
operational data using separate schemas or databases, whether connectors
run in Tempo or Maestro."

## Why this isn't mechanically implemented yet

SQLite — this codebase's only environment today — has no real multi-schema
support the way Oracle or Postgres do (`ATTACH DATABASE` approximates it at
the cost of real operational complexity for local dev). SQLAlchemy's
`__table_args__ = {"schema": "..."}` mechanism, which Oracle supports
natively as a user/schema namespace, would be untestable here — writing it
in now, unable to run it against anything, would violate this project's
own "build real, tested things" discipline. This document is the design
Phase 2's actual implementation (once ADR-0002's Oracle topology is
approved and a real environment exists) should execute against, categorised
now while the full table list is fresh from the tenant-isolation
inventory.

## Schema assignment

**`tempo_core`** — canonical workforce data, runs, actions, audit, and
this sprint's identity/membership tables. Owned by the application
runtime account with normal DML rights, no DDL:

`tenant_scope`, `labour_provider`, `worker`, `skill_certification`,
`availability`, `attendance_session`, `shift_assignment`, `demand_bucket`,
`zone_backlog`, `work_standard`, `activity_role_zone_map`,
`labour_cost_rule`, `sell_rate_contract`, `worker_performance_profile`,
`optimisation_policy`, `worker_credential`, `site_geofence`,
`optimisation_run`, `optimisation_run_site`, `optimisation_run_customer`,
`recommendation`, `action_request`, `source_version_watermark`,
`audit_record`, `event_record`, `tempo_user`, `tenant_membership`,
`user_role_assignment`, `user_site_grant`, `user_customer_grant`,
`user_provider_grant`, `kiosk_device`, `service_client`, `user_session`,
`privileged_support_grant`, `security_audit_event`.

**`tempo_integration`** — Maestro's own operational state (connector
plumbing), regardless of whether the connector runtime stays in-process
(today) or is extracted (ADR-0009). A connector service, wherever it runs,
should hold DML rights here and *no* access to `tempo_core` beyond what
the versioned canonical ingestion contract (INT-02) grants it:

`connector_checkpoint`, `maestro_connection`, `ingestion_dead_letter`.

## Why `audit_record`/`security_audit_event` stay in `tempo_core`, not a third schema

Tempting to give audit its own schema for tamper-resistance (SEC-10's
"protect audit records from normal application update and delete
operations") — but that's an Oracle *privilege* question (a role that can
`INSERT` but not `UPDATE`/`DELETE` on these two tables), not a schema
*location* question. Splitting schema by trust boundary (core app vs.
integration runtime) and splitting privilege by mutability (write-once
audit vs. normal CRUD) are two independent axes; conflating them into a
third schema adds a migration/deployment dimension without a matching
security benefit. SEC-10's actual implementation is a `GRANT` statement on
these two tables, applied in whichever schema they live in.

## What Phase 2's real implementation needs to do (once ADR-0002 lands)

1. Add `schema="tempo_core"` / `schema="tempo_integration"` to each
   model's `__table_args__` (or a metaclass/mixin if that reads better at
   the time — a decision for whoever implements this against a real
   Oracle environment, not fixed here).
2. Create the two Oracle schemas/users as part of environment
   provisioning (Phase 8's IaC), with `tempo_integration` granted no
   privileges on `tempo_core` tables beyond what INT-02's contract
   requires (likely: none directly — the connector runtime should talk to
   Tempo's API, not read/write `tempo_core` tables directly, once INT-01's
   adapter boundary is real).
3. Alembic (this sprint's `alembic/`) supports multiple schemas in one
   migration chain natively — no separate migration repository needed
   unless the two runtimes end up as genuinely separate deployables with
   separate release cadences (ADR-0009 territory).
4. Re-run `tests/test_migrations.py`'s upgrade/downgrade proof against a
   real Postgres or Oracle target once one exists, to catch anything
   SQLite's laxer type/constraint checking let through silently (DAT-01's
   own acceptance criterion).

## Acceptance criterion this unblocks

DAT-03's own: "Access and dependency review" — this document *is* that
review's starting artefact, not a replacement for actually running it
against a real environment.
