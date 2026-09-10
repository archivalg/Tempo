# Tenant Isolation Inventory (P0-mobilisation sprint deliverable)

Feeds SEC-03 ("Enforce tenant, site and customer filters on every read,
write, comparison, export and monitoring endpoint"), SEC-19/SEC-20
(Oracle VPD / composite-FK design), and ADR-0010 (Oracle VPD scope). Built
by auditing every model file and every `app/api/v1/*.py` endpoint against
`context.tenant_id`/`site_ids`/`customer_ids`/`provider_id` — a repo audit,
not a live-database test (that's `tests/test_tenant_isolation.py`, this
sprint's negative-test deliverable, and the real Oracle VPD tests Phase 2
will run against a live database per SEC-19's verification).

## 1. Every tenant-owned table and its scope columns

All 26 application tables carry `tenant_id` (verified by grep across
`app/models/*.py` — none omit it). The table below only lists the
*additional* scope columns beyond `tenant_id`, since that's where a VPD
policy needs a second predicate (ADR-0010).

| Table | Extra scope columns | Notes |
|---|---|---|
| `tenant_scope` | `site_id` (PK), `company_id`, `customer_id` | Registry itself, not operational data |
| `labour_provider` | — | Provider identity itself |
| `worker` | `home_site`, `provider_id` | `provider_id` nullable — only labour_hire workers |
| `skill_certification` | via `worker_id` FK | No direct site/customer column |
| `availability` | via `worker_id` FK | " |
| `attendance_session` | via `worker_id` FK | " |
| `shift_assignment` | via `worker_id` FK | " |
| `demand_bucket` | `site_id`, `customer_id` (nullable) | |
| `zone_backlog` | `site_id` | |
| `work_standard` | — | Tenant-wide config, no site column |
| `activity_role_zone_map` | `site_id` | |
| `labour_cost_rule` | — | Tenant-wide config |
| `sell_rate_contract` | `customer_id` (required) | |
| `worker_performance_profile` | via `worker_id` FK | |
| `optimisation_policy` | — | Tenant-wide config |
| `connector_checkpoint` | — (connection_id) | |
| `maestro_connection` | `site_id` | |
| `ingestion_dead_letter` | — (connection_id) | |
| `worker_credential` | via `worker_id` FK | |
| `site_geofence` | `site_id` (PK) | |
| `optimisation_run` | (see `RunRequest.scope`, not a column) | Scope is in the stored request JSON, not a queryable column — a gap for future indexed VPD filtering, not for correctness today |
| `recommendation` | via `run_id` | |
| `action_request` | (`target.site_id` inside JSON) | Same JSON-not-column gap as `optimisation_run` |
| `source_version_watermark` | `site_id` (PK) | |
| `audit_record` | — | |
| `event_record` | — | |
| **New this sprint** (`app/models/identity.py`) | | |
| `tenant_membership` | — | PK is `(user_id, tenant_id)` |
| `user_role_assignment` | — | |
| `user_site_grant` | `site_id` | |
| `user_customer_grant` | `customer_id` | |
| `user_provider_grant` | `provider_id` | |
| `kiosk_device` | `site_ids` (JSON list) | Not a normalised column — fine for app-layer checks, would need a join table for a real VPD predicate |
| `service_client` | `site_ids` (JSON list, nullable) | Same JSON caveat |
| `privileged_support_grant` | `target_tenant_id`, `site_ids` (JSON) | |
| `security_audit_event` | `tenant_id` nullable (a platform-level event has none) | |

**Gap for Phase 2 to resolve**: `optimisation_run.RunRequest.scope` and
`action_request.target` store site/customer scope inside a JSON blob, not
a queryable column. Every current endpoint still filters correctly
because it reads the JSON and compares in Python — but a VPD policy (which
operates at the SQL layer) cannot see into a JSON blob the same way.
DAT-05's index/partition design and SEC-19's VPD package need this
resolved (likely: promote `site_id`/`customer_id` to real columns on these
two tables) before those two tables can gain a real VPD predicate beyond
`tenant_id`.

## 2. Every endpoint and its current scope enforcement

| Endpoint(s) | File | Tenant check | Site check | Customer check | Provider check |
|---|---|---|---|---|---|
| All `runs.py` endpoints | `runs.py` | ✅ every read via `_get_owned_run` (tenant match or 404) | ✅ `_enforce_scope` on create (fixed this sprint — see §3) | ✅ `_enforce_scope` on create (fixed this sprint) | n/a |
| All `actions.py` endpoints | `actions.py` | ✅ `_get_owned_action`/tenant match | ✅ on validate (fixed this sprint) | — (no customer dimension on actions today) | n/a |
| All `attendance.py` endpoints | `attendance.py` | ✅ (`context.tenant_id` on every query) | ✅ clock-in and site-attendance read (fixed this sprint); `GET /workers/{id}/shifts` and `whoami` are **tenant-only**, disclosed (see below) | — | n/a |
| All `onboarding.py` endpoints | `onboarding.py` | ✅ | — (site is the resource being registered, not a caller restriction — correct for a Tenant Admin) | — | n/a |
| All `providers.py` endpoints | `providers.py` | ✅ `_get_owned_provider` | ✅ worker registration (fixed this sprint) | n/a | ✅ `_require_provider_access` |
| `monitoring.py` | `monitoring.py` | ✅ | — (tenant-wide by design, matches `labour.read`'s "aggregates" framing) | — | n/a |
| `readiness.py` | `readiness.py` | ✅ | — (same as monitoring) | — | n/a |

## 3. Finding: the `context.X and Y not in context.X` pattern (fixed this sprint)

Five call sites — `runs.py::_enforce_scope`, `actions.py::validate_action`,
`attendance.py::clock_in_endpoint`, `attendance.py::get_site_attendance`,
`providers.py::register_supplied_worker` — read:

```python
if context.site_ids and request.site_id not in context.site_ids:
    raise ScopeError(...)
```

This is exactly the anti-pattern §6.4 names: *"An empty set means no
access and must never mean no filter."* Python's `and` short-circuits, so
when `context.site_ids` is empty (falsy), the whole condition is `False`
and **no check runs at all** — a caller whose header carried an empty
`site_ids` (legal today: `app/dependencies.py` only requires *one* of
`site_ids`/`customer_ids` to be non-empty) passed every site check in the
codebase unconditionally, regardless of which site they named.

Concretely: a caller presenting `{"site_ids": [], "customer_ids": ["cust_A"], "roles": ["operations_manager"]}`
— a header that passes `get_request_context`'s own validation — could
create a run, validate an action, or clock a worker in/out **at any site
in the tenant**, not just sites they were meant to be restricted to.

**Fixed this sprint** by removing the truthy guard at all five call sites,
so an empty `context.site_ids` now denies every site-scoped request,
matching AccessScope's `authorises_site` (`app/core/access_scope.py`)
which was written correctly from the start (`site_id in scope.site_ids`,
no short-circuit). Regression tests: `tests/test_tenant_isolation.py`'s
`test_empty_site_ids_denies_rather_than_skips_the_check` and its
`_enforce_scope`-specific siblings. No existing test relied on the old
behaviour — confirmed by grep across `tests/*.py` before the fix (see the
sprint-review notes for the exact check run).

This finding, not a hypothetical one, is the concrete reason SEC-03's
"cross-tenant test suite" and SEC-19's Oracle VPD (ADR-0010) both matter:
an application-layer predicate bug like this is exactly what VPD exists to
catch as a second, independent layer, per §6.5's "VPD is the independent
containment layer for missed predicates and unsafe future code."

## 4. Findings not fixed this sprint (documented, not actioned without approval)

- **`GET /v1/workers/{worker_id}/shifts` and `POST /v1/attendance/whoami`**
  are tenant-scoped only — any caller in the tenant can view any worker's
  shifts or resolve any worker by PIN/NFC, by the endpoint's own explicit
  docstring ("no per-worker identity exists yet... any caller in the
  tenant's scope can view any worker's shifts"). This is disclosed,
  pre-existing behaviour, not something this sprint's fix touched — closing
  it needs the Worker principal type's worker-self authority
  (`AccessScope.worker_self_id`, built this sprint) to actually gate this
  endpoint, which needs a worker to *authenticate* as themselves first
  (Phase 1's remaining, IdP-dependent work).
- **`optimisation_run`/`action_request`'s JSON-embedded scope** (§1's table
  above) — not a correctness gap today (Python-level filtering still
  works), but a blocker for Oracle VPD coverage of these two tables until
  Phase 2 promotes the relevant fields to real columns.
- **The entire header mechanism remains unverified** — every fix in this
  document only matters once a real caller can't simply set
  `X-Tempo-Context` to whatever they want. This document audits what the
  *application logic* does given a trusted context; it does not, and
  cannot, close SEC-01/SEC-02 (real token verification) — that's ADR-0001
  and the identity/session work this sprint deliberately left for
  approval.
