import { apiRequest, downloadFile, newIdempotencyKey } from './client'

export interface DataSource { key: string; label: string; kind: string; mode: string; declared_mode: string; last_success_at: string | null; age_seconds: number | null; fresh: boolean; note: string | null }
export interface SiteSummary { site_id: string; name: string; timezone: string; operating_mode: string; is_synthetic: boolean; data_sources: DataSource[]; all_sources_fresh: boolean }
export interface Kpi { key: string; label: string; value: number | null; display: string; unit: string; numerator: number | null; denominator: number | null; definition: string; basis: string; status: string; reason: string | null; drill: string }
export interface HourPoint { hour_start: string; actual_units: number | null; forecast_units: number | null; forecast_lower: number | null; forecast_upper: number | null; capacity_units: number | null; staffed_hours: number; required_hours: number | null; source: { actual: string; forecast: string | null }; confidence: unknown }
export interface HeatCell { zone: string; zone_name: string; shift: string; required_hours: number; staffed_hours: number; status: 'covered' | 'risk' | 'shortage' | 'no_demand'; label: string }
export interface ExceptionItem { id: string; kind: string; severity: string; state: string; site_id: string; worker_id: string | null; worker_label: string | null; shift_id: string | null; source_occurred_at: string; detected_at: string; age_seconds: number; detection_lag_seconds: number; owner_user_id: string | null; resolution: string | null; evidence: Record<string, unknown> }
export interface Recommendation { recommendation_id: string; run_id: string; title: string; moves: { from_zone: string; to_zone: string }[]; impact: { remaining_backlog: number | null; coverage_pct: number | null; baseline: Record<string, unknown> | null }; created_at: string; expires_at: string; stale: boolean }
export interface Overview {
  site: { site_id: string; name: string; timezone: string; operating_mode: string; is_synthetic: boolean; local_now: string }
  day: string; as_of: string; metric_version: string; data_sources: DataSource[]; attendance_verified: boolean
  forecast: { run_id: string | null; method: string | null; confidence: Record<string, unknown> | null; created_at: string | null }
  kpis: Kpi[]; hourly: HourPoint[]
  heatmap: { zones: { zone_id: string; name: string }[]; shifts: { code: string; start: string; end: string }[]; cells: HeatCell[] }
  attention: ExceptionItem[]; roster_preview: { label: string; date: string; shifts: number; workers: number; state: string; approval: string | null }[]
  recommendations: Recommendation[]
}
export interface RosterShift { shift_id: string; worker_id: string; role: string; zone: string; start_at: string; end_at: string; status: string; employment_type: string; break_minutes: number; flags: string[] }
export interface RosterTotals { shifts: number; workers: number; hours: number; agency_share_pct: number | null; cost?: number | null; cost_note?: string | null }
export interface Roster {
  site: { site_id: string; name: string; timezone: string; operating_mode: string }
  range: { start: string; days: number }; as_of: string; view: 'published' | 'draft'; has_draft: boolean
  workers: { worker_id: string; label: string; employment_type: string; skills: string[]; provider_id: string | null }[]
  shifts: RosterShift[]
  coverage_band: { date: string; required_hours: number | null; rostered_hours: number; status: string | null }[]
  conflicts: { kind: string; severity: string; shift_id: string; worker_id: string | null; detail: string }[]; hard_conflicts: number
  totals: { published: RosterTotals; draft: RosterTotals }
  publication: { latest_action_status: string | null; latest_action_id: string | null; can_publish: boolean }
  forecast: { run_id: string | null; method: string }; notes: string[]
}
export interface LiveRow { shift_id: string | null; worker_id: string; worker_label: string; role: string | null; zone: string | null; scheduled_start: string | null; scheduled_end: string | null; punch_in: string | null; punch_out: string | null; state: string; minutes_late: number | null; approval: string | null; attendance_session_id: string | null }
export interface Live {
  site: { site_id: string; name: string; timezone: string; operating_mode: string; local_now: string }
  as_of: string; attendance_verified: boolean; data_sources: DataSource[]
  counts: { expected: number; present: number | null; late: number | null; absent: number | null; unrostered: number | null }
  definitions: Record<string, string>; rows: LiveRow[]; exceptions: ExceptionItem[]; stale_message: string | null
}

export const listSites = () => apiRequest<SiteSummary[]>('/sites')
export const getOverview = (site: string, date?: string) => apiRequest<Overview>(`/sites/${site}/overview${date ? `?date=${date}` : ''}`)
export const getRoster = (site: string, start?: string, view?: string) =>
  apiRequest<Roster>(`/sites/${site}/roster?${new URLSearchParams({ ...(start ? { start } : {}), ...(view ? { view } : {}) })}`)
export const getLive = (site: string) => apiRequest<Live>(`/sites/${site}/attendance/live`)
export const detectExceptions = (site: string) => apiRequest<{ new_cases: Record<string, number> }>(`/sites/${site}/exceptions/detect`, { method: 'POST' })
export const acknowledgeException = (id: string) => apiRequest(`/exceptions/${id}/acknowledge`, { method: 'POST' })
export const assignException = (id: string) => apiRequest(`/exceptions/${id}/assign`, { method: 'POST' })
export const resolveException = (id: string, reason: string, dismiss = false) =>
  apiRequest(`/exceptions/${id}/${dismiss ? 'dismiss' : 'resolve'}`, { method: 'POST', body: { reason } })

export function generateDraftRoster(tenantId: string, siteId: string, customerIds: string[], weekStartIso: string, policyVersion?: string) {
  const start = new Date(weekStartIso)
  const end = new Date(start.getTime() + 7 * 86400000)
  return apiRequest<{ run_id: string; status: string; recommendation_id: string }>('/optimisations/named_roster', {
    method: 'POST', idempotencyKey: newIdempotencyKey(),
    body: {
      request_id: `req_${newIdempotencyKey().slice(0, 12)}`,
      scope: { tenant_id: tenantId, site_ids: [siteId], customer_ids: customerIds },
      planning_window: { start: start.toISOString(), end: end.toISOString(), timezone: 'UTC', bucket_minutes: 1440 },
      configuration: policyVersion ? { policy_version: policyVersion } : {},
    },
  })
}

// ---- roster versions (draft → submit → approve → publish) ----
export interface RosterVersion { id: string; site_id: string; week_start: string; days: number; version_no: number; state: string; source: string; source_run_id: string | null; parent_version_id: string | null; created_by: string; created_at: string; submitted_by: string | null; submitted_at: string | null; approved_by: string | null; approved_at: string | null; decision_note: string | null; published_at: string | null; published_by: string | null; reconciliation: { checks?: Record<string, boolean>; committed?: number; version_rows?: number }; payload_hash: string | null }
export interface VersionBoard extends Roster { version: RosterVersion; versions: RosterVersion[] }
export interface PendingRoster extends RosterVersion { site_name: string; age_seconds: number; impact: { this_version: RosterTotals; current_published: RosterTotals; hard_conflicts: number } | null }
export interface RosterEventItem { at: string; actor: string; action: string; detail: Record<string, unknown> }
export interface ShiftInput { worker_id: string; role: string; zone: string; start_at: string; end_at: string }

export const listRosterVersions = (site: string, weekStart: string) => apiRequest<RosterVersion[]>(`/sites/${site}/rosters?week_start=${weekStart}`)
export const getVersionBoard = (id: string) => apiRequest<VersionBoard>(`/rosters/${id}`)
export const getVersionEvents = (id: string) => apiRequest<RosterEventItem[]>(`/rosters/${id}/events`)
export const generateRoster = (site: string, weekStart: string) => apiRequest<VersionBoard>(`/sites/${site}/rosters/generate`, { method: 'POST', body: { week_start: weekStart } })
export const copyPublished = (site: string, weekStart: string) => apiRequest<VersionBoard>(`/sites/${site}/rosters/copy-published`, { method: 'POST', body: { week_start: weekStart } })
export const addShift = (id: string, s: ShiftInput) => apiRequest<VersionBoard>(`/rosters/${id}/shifts`, { method: 'POST', body: s })
export const editShift = (id: string, shiftId: string, s: Partial<ShiftInput>) => apiRequest<VersionBoard>(`/rosters/${id}/shifts/${shiftId}`, { method: 'PATCH' , body: s })
export const deleteShift = (id: string, shiftId: string) => apiRequest<VersionBoard>(`/rosters/${id}/shifts/${shiftId}`, { method: 'DELETE'  })
export const submitRoster = (id: string) => apiRequest<RosterVersion>(`/rosters/${id}/submit`, { method: 'POST' })
export const approveRoster = (id: string, note: string) => apiRequest<RosterVersion>(`/rosters/${id}/approve`, { method: 'POST', body: { note } })
export const rejectRoster = (id: string, note: string) => apiRequest<RosterVersion>(`/rosters/${id}/reject`, { method: 'POST', body: { note } })
export const publishRoster = (id: string) => apiRequest<RosterVersion>(`/rosters/${id}/publish`, { method: 'POST', idempotencyKey: newIdempotencyKey() })
export const listPendingRosters = () => apiRequest<PendingRoster[]>('/rosters/pending')

// ---- attendance / timesheets ----
export interface Timesheet { session_id: string; worker_id: string | null; worker_label: string; clock_in: string; clock_out: string | null; open: boolean; approval: string; scheduled_start: string | null; scheduled_end: string | null; role: string | null; matched: boolean; punched_hours: number; scheduled_hours: number; payable_hours: number | null; adjustment: { id: string; state: string; requested_start: string; requested_end: string | null; reason: string; requested_by: string; decision_note: string | null } | null }
export interface TimesheetData { range: { start: string; days: number }; as_of: string; sessions: Timesheet[]; summary: { sessions: number; open: number; approved: number; pending: number; unrostered: number; pending_adjustments: number } }
export const getTimesheets = (site: string, start?: string, days = 7) => apiRequest<TimesheetData>(`/sites/${site}/timesheets?${new URLSearchParams({ ...(start ? { start } : {}), days: String(days) })}`)
export const approveSession = (id: string) => apiRequest(`/attendance/sessions/${id}/approve`, { method: 'POST' })
export const requestAdjustment = (id: string, requested_start: string, requested_end: string, reason: string) => apiRequest(`/attendance/sessions/${id}/adjustments`, { method: 'POST', body: { requested_start, requested_end, reason } })
export const decideAdjustment = (id: string, approve: boolean, note: string) => apiRequest(`/attendance/adjustments/${id}/${approve ? 'approve' : 'reject'}`, { method: 'POST', body: { note } })

// ---- variance + demand ----
export interface VarianceDay { date: string; complete: boolean; status: 'complete' | 'in_progress' | 'upcoming'; scheduled_hours: number; attended_hours: number; payable_hours: number; variance_hours: number; shifts_due: number | null; shifts_matched: number | null; adherence_pct: number | null; late: number | null; no_shows: number | null; overtime_hours: number; forecast_units: number | null; actual_units: number | null; forecast_ape_pct: number | null; productivity_units_per_hour: number | null; planned_cost?: number; estimated_actual_cost?: number; confirmed_cost?: number }
export interface Variance { range: { start: string; days: number }; as_of: string; attendance_verified: boolean; data_sources: DataSource[]; days: VarianceDay[]; totals: Record<string, number | null>; definitions: Record<string, string>; forecast: { run_id: string | null; method: string }; notes: string[]; metric_version: string }
export const getVariance = (site: string, start?: string) => apiRequest<Variance>(`/sites/${site}/reports/variance${start ? `?start=${start}` : ''}`)
export interface DemandRow { date: string; activity: string; actual_units: number | null; forecast_units: number | null; forecast_lower: number | null; forecast_upper: number | null; model_units?: number | null; adjusted?: boolean; seconds_per_unit: number | null; required_hours: number | null }
export interface Demand { range: { start: string; days: number }; rows: DemandRow[]; activities: string[]; standards: { activity: string; seconds_per_unit: number; effective_from: string }[]; zone_map: { activity: string; role: string; zone: string; weight: number }[]; readiness: { check: string; ok: boolean; detail: string }[]; data_sources: DataSource[]; forecast: { run_id: string | null; created_at: string | null; snapshot_id: string | null; method: string; backtest_mape: number | null; confidence: Record<string, unknown> | null }; overrides_note: string; overrides: DemandOverride[] }
export const getDemand = (site: string, start?: string) => apiRequest<Demand>(`/sites/${site}/demand${start ? `?start=${start}` : ''}`)

export const exportCsv = (site: string, kind: 'variance' | 'timesheets' | 'demand', start: string) => downloadFile(`/sites/${site}/exports/${kind}.csv?start=${start}`)

export interface DemandOverride { id: string; site_id: string; activity: string | null; start_date: string; end_date: string; mode: 'multiply' | 'set_units'; value: number; reason: string; origin: string; status: 'active' | 'expired' | 'revoked'; expires_at: string; created_by: string; created_at: string; revoked_by: string | null; revoked_at: string | null; revoke_reason: string | null }
export interface NewOverride { activity: string | null; start_date: string; end_date: string; mode: 'multiply' | 'set_units'; value: number; reason: string; expires_at: string }
export const createOverride = (site: string, body: NewOverride) => apiRequest<DemandOverride>(`/sites/${site}/demand/overrides`, { method: 'POST', body })
export const revokeOverride = (id: string, reason: string) => apiRequest<DemandOverride>(`/demand/overrides/${id}/revoke`, { method: 'POST', body: { reason } })
