# Data Retention Policy (DAT-07, draft)

Status: **draft policy, no enforcement jobs yet** — enforcement (actually
deleting/archiving rows on schedule) needs Phase 4's scheduler (JOB-08);
this document defines the windows a real job would apply once one exists.
Every window below is a starting recommendation, not an approved
retention requirement — DAT-07's own dependency list names "retention
requirements from legal and customers" as the actual source of truth this
must be checked against before a real job enforces it.

## Retention windows by data class

| Data class | Tables | Proposed retention | Rationale |
|---|---|---|---|
| Attendance | `attendance_session`, `worker_credential` (audit trail only, not the credential itself) | 7 years | Common payroll/labour-law record-keeping horizon in AU/NZ jurisdictions (Fair Work Act record-keeping requirements are 7 years) — confirm against the pilot's actual jurisdiction before treating this as fixed. |
| Demand / operational | `demand_bucket`, `zone_backlog` | 2 years | Long enough to backtest a full seasonal cycle twice over (MOD-07/PIL-03); no known regulatory driver, purely a modelling-usefulness window. |
| Solver results | `optimisation_run`, `optimisation_snapshot`, `recommendation`, `optimisation_run_site`, `optimisation_run_customer` | 3 years | Covers a rejected/disputed recommendation's likely dispute window; also the natural horizon for MOD-08's rollback and reproducibility guarantees to matter in practice. |
| Actions / writeback | `action_request` | 7 years | Same record-keeping horizon as attendance — an executed writeback is an operational HR/payroll-adjacent action. |
| Audit | `audit_record`, `security_audit_event` | 7 years, **never auto-deleted before then** | SEC-10: "Define audit retention and protect audit records from normal application update and delete operations." A shorter window here would itself be a control failure, not a storage optimisation. |
| Dead letters | `ingestion_dead_letter` | 90 days after resolution, 1 year if never resolved | Long enough to investigate a stuck backlog; unresolved dead letters older than a year need an operational escalation, not indefinite silent retention. |
| Integration payloads | Any raw vendor payload the eventual integration service logs (Phase 3 — no such table exists yet in this codebase) | 30 days | Vendor payloads are re-fetchable from source; long retention here is pure liability (may contain worker PII) for no operational benefit once ingested and quarantine-checked. |
| Identity / session | `user_session` (revoked/expired rows), `security_audit_event`'s session references | 1 year after revocation/expiry | Session forensics window; the live session itself is governed by SEC-15's token lifetime, not this policy. |
| Privileged support grants | `privileged_support_grant` | 7 years, never auto-deleted | Same reasoning as audit — a support grant's record *is* an audit artefact (SEC-24). |

## What this does not cover yet

- **Enforcement mechanism**: a real retention job (Phase 4's scheduler,
  JOB-08) that actually archives/deletes rows on these schedules doesn't
  exist. This table is the policy that job would read, not the job.
- **Legal/customer-specific overrides**: this is a single default policy;
  a real deployment likely needs per-tenant or per-jurisdiction overrides
  (e.g. a EU customer's GDPR-driven worker-data retention limits, which
  may be *shorter* than the payroll-record-keeping floor above and would
  need reconciling, not just picking the smaller number blindly).
- **Archival vs. deletion**: this document doesn't yet distinguish "delete"
  from "move to cold storage" — DAT-07's own acceptance test ("retention
  job test") is where that distinction needs to be made concrete.
