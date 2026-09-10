// Mirrors services/tempo-api/app/schemas/{runs,actions,onboarding,tenancy}.py.
// Kept as plain interfaces, not generated — the backend has no OpenAPI
// codegen step wired up yet (a reasonable follow-up once this shape churns
// less).

export const RUN_TYPES = [
  'demand_forecast',
  'labour_requirement',
  'workforce_mix',
  'named_roster',
  'intraday_reallocation',
  'training_coverage',
  'leave_rdo',
  'team_composition',
  'margin_3pl',
  'scenario',
] as const
export type RunType = (typeof RUN_TYPES)[number]

export const OBJECTIVE_PROFILES = ['lowest_cost', 'best_service', 'balanced', 'lowest_risk', 'custom_policy'] as const
export type ObjectiveProfile = (typeof OBJECTIVE_PROFILES)[number]

// Mirrors app/schemas/actions.py's ACTION_TYPE_RUN_TYPE — which
// run_type's recommendation each action_type is allowed to act on.
export const ACTION_TYPE_BY_RUN_TYPE: Record<string, string> = {
  named_roster: 'publish_roster',
  intraday_reallocation: 'update_assignment',
  leave_rdo: 'approve_leave',
  training_coverage: 'create_training_plan',
}

export interface TempoContext {
  tenant_id: string
  company_id?: string
  site_ids: string[]
  customer_ids: string[]
  user_id: string
  roles: string[]
  purpose: string
  correlation_id: string
}

export interface RunListItem {
  run_id: string
  run_type: string
  status: string
  created_at: string
  completed_at: string | null
}

export interface RunListResponse {
  runs: RunListItem[]
  next_cursor: string | null
}

export interface RunCreateResponse {
  run_id: string
  run_type: string
  status: string
  created_at: string
  links: { self: string; cancel: string }
  input_snapshot_id: string
  effective_scope: { tenant_id: string; site_ids: string[]; customer_ids: string[] }
  warnings: string[]
  recommendation_id: string | null
}

export interface Confidence {
  score: number
  band: string
  method: string
  components: Record<string, number>
  reasons: string[]
}

export interface Explanation {
  baseline: Record<string, unknown>
  proposed: Record<string, unknown>
  delta: Record<string, unknown>
  dollar_value: { amount: string; currency: string } | null
  confidence: Confidence
  primary_drivers: string[]
  alternatives: Record<string, unknown>[]
  data_lineage: Record<string, unknown>
  freshness: Record<string, unknown>
  missing_evidence: string[]
  assumptions: string[]
  feasibility: string
  evidence_ref: string
}

export interface RunDetail {
  run_id: string
  status: string
  run_type?: string
  model?: { name: string; version: string; solver: string }
  result?: Record<string, unknown>
  explanation?: Explanation
  lineage?: Record<string, unknown>
  completed_at?: string | null
  created_at?: string
  input_snapshot_id?: string
  recommendation_id?: string | null
}

// Mirrors app/api/v1/runs.py's compare_runs response — one KPI object per
// requested run_id, in the same order requested.
export interface RunComparisonResponse {
  run_ids: string[]
  kpis: { run_id: string; kpis: Record<string, unknown> }[]
}

export interface ActionListItem {
  action_id: string
  action_type: string
  recommendation_id: string
  status: string
  created_at: string
}

export interface ActionListResponse {
  actions: ActionListItem[]
  next_cursor: string | null
}

export interface ActionTarget {
  system: string
  connection_id: string
  site_id: string
}

export interface ActionValidateResponse {
  action_id: string
  action_token: string
  status: string
  impact_summary: Record<string, unknown>
  expires_at: string
}

export interface ActionResponse {
  action_id: string
  status: string
  detail: string | null
}

export interface ActionDetail {
  action_id: string
  action_type: string
  recommendation_id: string
  target: ActionTarget
  status: string
  detail: string | null
  approver_id: string | null
  created_at: string
  updated_at: string
}

export interface ConnectorDescriptor {
  source_system: string
  display_name: string
  entity_types: string[]
  auth_type: string
  status: string
  notes: string
}

export interface TenantScope {
  tenant_id: string
  site_id: string
  company_id: string | null
  customer_id: string | null
  created_at: string
}

export interface Connection {
  connection_id: string
  tenant_id: string
  source_system: string
  site_id: string
  display_name: string | null
  status: string
  created_at: string
}

export interface ModelMonitoringMetrics {
  run_count: number
  solver_gap_rate: number
  failure_rate: number
  avg_confidence: number | null
  avg_backtest_mape: number | null
  model_version_adoption: Record<string, number>
}

export interface DriftSignal {
  run_type: string
  metric: string
  baseline: number
  recent: number
}

export interface DataReadiness {
  status: string
  score: number
  as_of: string
  required_domains: { domain: string; status: string; freshness_seconds?: number; warning?: string }[]
  blocking_issues: string[]
  warnings: string[]
}

// Mirrors app/schemas/attendance.py — Business Spec §4/§5's Standalone
// native capture path (PIN/NFC clock-in, no per-worker identity yet).
export type ClockMethod = 'pin' | 'nfc'

export interface CredentialEnrollResponse {
  worker_id: string
  has_pin: boolean
  has_nfc: boolean
}

export interface WhoamiResponse {
  worker_id: string
  employment_type: string
  home_site: string
  has_open_session: boolean
}

export interface ClockInResponse {
  worker_id: string
  attendance_session_id: string
  clocked_in_at: string
  geofence_status: 'passed' | 'skipped'
  matched_rostered_shift: boolean
}

export interface ClockOutResponse {
  worker_id: string
  attendance_session_id: string
  clocked_in_at: string
  clocked_out_at: string
  duration_minutes: number
}

export interface UpcomingShift {
  shift_id: string
  role: string
  zone: string
  start_at: string
  end_at: string
  status: string
}

export interface SiteAttendanceEntry {
  worker_id: string
  attendance_session_id: string
  clocked_in_at: string
  clocked_out_at: string | null
  matched_rostered_shift: boolean
}
