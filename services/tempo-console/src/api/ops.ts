import { apiRequest, newIdempotencyKey } from './client'

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
