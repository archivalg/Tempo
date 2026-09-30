# ADR-0011: PostgreSQL with row-level security (supersedes 0002 and 0010)

**Status**: Accepted — 30 September 2026 (owner decision, Blueprint v1.2)
**Supersedes**: [0002](0002-oracle-topology.md) (Oracle topology), [0010](0010-oracle-vpd-scope.md) (Oracle VPD scope)

## Decision

Tempo uses **PostgreSQL 16** in local, test, pre-production and production, in its **own database with its own
credentials**, separate from any other product. Oracle Autonomous Database and VPD are out of scope. The
application stack stays Python 3.12 / FastAPI / SQLAlchemy 2 / Alembic and React 19 / TypeScript, matching the
versions used across Ensemble products for supportability. Hosting (OCI or otherwise) is a separate decision and
does not dictate the database engine. There is no runtime dependency on, connector to, or federation with any
other product.

## Containment model

* Two database roles: **`tempo_owner`** (owns schema objects, runs Alembic migrations only) and **`tempo_app`**
  (API/worker runtime: owns nothing, `NOBYPASSRLS`, not superuser, no DDL). Connector runtime gets its own role
  when it is split out (tracked in the ledger).
* Every table with `tenant_id` has `ENABLE ROW LEVEL SECURITY` and a policy
  `tenant_id = current_setting('app.tenant_id', true)` for `USING` and `WITH CHECK`. A missing or empty setting
  evaluates to NULL, so **no rows match and no write is permitted (fail closed)**. A test fails the build if a new
  tenant table lacks RLS.
* The setting is transaction-local (`set_config(..., true)`), applied on every transaction begin by
  `app/db.py` after — and only after — the caller is authenticated (`bind_tenant`). Pooled connections cannot
  carry a tenant into the next request. Background work uses `tenant_session(tenant_id)`.
* Identity tables needed to *resolve* a principal (sessions, users, memberships, grants, devices) are readable
  only during an explicit auth-lookup phase (`app.auth_lookup='on'`), which is set solely by `app/core/auth.py`
  and `app/core/kiosk.py`, and cleared when the tenant is bound. This is a containment layer against
  under-filtered application queries, not a defence against arbitrary SQL injection.
* Audit tables (`security_audit_event`, `audit_record`, `event_record`) are append-only for the runtime role
  (no UPDATE/DELETE/TRUNCATE grants).
* Application predicates (`WHERE tenant_id = …`, site/customer/provider checks) remain mandatory for behaviour
  and performance; RLS is the independent second layer.
* RLS is `ENABLE`d, not `FORCE`d: owners bypass RLS, which is acceptable because the owner role is used only by
  migrations and test fixtures and never by a running service. Revisit `FORCE` if an owner-role service is added.

## Not yet done (tracked, not accepted)

* Site/customer/provider-level RLS (subordinate scope): today only tenant is enforced in the database; subordinate
  scope is enforced by `AccessScope`/handler checks.
* `worker.worker_id` (and other legacy PKs) are globally unique rather than tenant-aware; needs a composite-key
  migration before multi-tenant data volumes.
* Backup/restore, PITR, TLS to the database, and vault-held credentials are unverified until infrastructure exists.
  The readiness spec's **15-minute RPO / 4-hour RTO are provisional planning assumptions**, not accepted targets,
  until approved and demonstrated by a restore test.

## Consequences

Migrations are PostgreSQL-only; SQLite is no longer a supported application or test environment.
