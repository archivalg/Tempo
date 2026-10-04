import { apiRequest } from './client'

export interface PlanDef { id: string; plan_key: string; version: number; name: string; monthly_price_per_site_aud: number | null; entitlements: Record<string, boolean>; status: 'draft' | 'approved' | 'retired'; notes: string; created_by: string | null; approved_by: string | null; indicative: boolean }
export interface TenantRow { tenant_id: string; name: string; status: string; created_at: string; managed: boolean; plan: string | null; billing_source: string | null; manual_kind: string | null; subscription_status: string | null; licensed_sites: number | null; sites_in_use: number; worker_band: string | null; active_workers: number; allowance_state: 'ok' | 'near' | 'over' | null; expires_at: string | null }
export interface SubscriptionInput { plan_key: string; licensed_sites: number; worker_band: string; manual_kind: string; discount_pct: number; reason: string; reference?: string | null; expires_at?: string | null }
export interface SupportGrant { grant_id: string; operator_user_id: string; target_tenant_id: string; reason: string; site_ids: string[]; action_categories: string[]; approved_at: string; expires_at: string; terminated_at: string | null; state: 'live' | 'terminated' | 'expired' }
export interface AuditRow { event_id: string; at: string; actor_type: string; actor_id: string; tenant_id: string | null; action: string; decision: string; reason_code: string | null }

export type EmailOutcome = 'sent' | 'failed' | 'not_configured' | 'no_address'
export interface SmtpView { enabled: boolean; host: string; port: number; security: 'starttls' | 'ssl' | 'none'; username: string; has_password: boolean; from_email: string; from_name: string; configured: boolean; updated_by: string | null; updated_at: string | null; last_test_at: string | null; last_test_ok: boolean | null; last_test_detail: string | null }
export interface SmtpInput { enabled: boolean; host: string; port: number; security: string; username: string; password?: string; from_email: string; from_name: string }
export interface EmailLog { id: string; at: string; to: string; subject: string; kind: string; status: string; error: string | null; tenant_id: string | null }
export const getEmailConfig = () => apiRequest<SmtpView>('/platform/email')
export const putEmailConfig = (body: SmtpInput) => apiRequest<SmtpView>('/platform/email', { method: 'PUT', body })
export const testEmailConnection = () => apiRequest<{ ok: boolean; detail: string }>('/platform/email/test-connection', { method: 'POST' })
export const sendTestEmail = (to: string) => apiRequest<{ sent: boolean; detail: string }>('/platform/email/send-test', { method: 'POST', body: { to } })
export const emailMessages = () => apiRequest<EmailLog[]>('/platform/email/messages')
/** What to tell the administrator about an invitation email: the one-time link is always shown too. */
export const emailedNote = (e: EmailOutcome | null | undefined, to?: string) => e === 'sent' ? `We also emailed it to ${to ?? 'them'}.` : e === 'failed' ? 'We tried to email it but the mail server did not accept it (see Email), so send the link yourself.' : e === 'not_configured' ? 'Email is not set up (Email page), so send the link yourself.' : ''

export const listPlans = () => apiRequest<PlanDef[]>('/platform/plans')
export const newPlanVersion = (body: { plan_key: string; name: string; monthly_price_per_site_aud: number | null; notes: string }) => apiRequest<PlanDef>('/platform/plans', { method: 'POST', body })
export const approvePlan = (id: string) => apiRequest<PlanDef>(`/platform/plans/${id}/approve`, { method: 'POST' })
export const tenantOverview = (q: string) => apiRequest<TenantRow[]>(`/platform/tenant-overview${q ? `?q=${encodeURIComponent(q)}` : ''}`)
export const createTenant = (body: { tenant_id: string; name: string; first_admin: { email: string }; initial_site_ids: string[]; subscription?: SubscriptionInput }) =>
  apiRequest<{ tenant_id: string; invite_path: string | null; emailed: EmailOutcome | null }>('/platform/tenants', { method: 'POST', body })
export const setSubscription = (tenant: string, body: SubscriptionInput) => apiRequest(`/platform/tenants/${tenant}/subscription`, { method: 'PUT', body: { billing_source: 'manual', ...body } })
export const setTenantStatus = (tenant: string, status: 'active' | 'suspended') => apiRequest(`/platform/tenants/${tenant}/status?status=${status}`, { method: 'POST' })
export const subscriptionHistory = (tenant: string) => apiRequest<{ at: string; actor: string; action: string; reason: string }[]>(`/platform/tenants/${tenant}/subscription-history`)
export const listGrants = () => apiRequest<SupportGrant[]>('/platform/support-grants')
export const createGrant = (body: { target_tenant_id: string; reason: string; hours: number; action_categories: string[]; site_ids: string[] }) => apiRequest<{ grant_id: string }>('/platform/support-grants', { method: 'POST', body })
export const endGrant = (id: string) => apiRequest(`/platform/support-grants/${id}/terminate`, { method: 'POST' })
export const platformAudit = () => apiRequest<AuditRow[]>('/platform/audit?limit=100')
export const addPlatformAdmin = (email: string) => apiRequest<{ user_id: string; invite_path: string | null; emailed: EmailOutcome | null }>('/platform/admins', { method: 'POST', body: { email } })

export interface Diagnostics {
  session: { grant_id: string; tenant_id: string; reason: string; site_ids: string[]; expires_at: string; mode: string }
  tenant: { tenant_id: string; name: string; status: string }
  plan: Record<string, unknown> & { managed: boolean; message?: string; plan?: { name: string }; allowance_state?: string; active_workers: number; sites_in_use: number; licensed_sites?: number }
  sites: { site_id: string; name: string; timezone: string; operating_mode: string }[]
  workers_by_status: Record<string, number>; open_attendance_sessions: number; open_exceptions_by_kind: Record<string, number>
  rosters: { site_id: string; week_start: string; version_no: number; state: string; source: string }[]
  imports: { data_class: string; entity: string | null; channel: string; state: string; rows: number; errors: number; at: string }[]
  connections: { source_system: string; site_id: string; status: string }[]
  recent_security_events: { at: string; actor_type: string; action: string; decision: string; reason: string | null }[]
  limits: string
}
export const openSupport = (grant: string) => apiRequest<Diagnostics['session']>(`/platform/support-grants/${grant}/open`, { method: 'POST' })
export const getDiagnostics = (grant: string) => apiRequest<Diagnostics>(`/platform/support/${grant}/diagnostics`)
export const inviteTenantAdmin = (tenant: string, email: string) => apiRequest<{ invite_path: string; sites: string[]; emailed: EmailOutcome | null }>(`/platform/tenants/${tenant}/admins`, { method: 'POST', body: { email } })
