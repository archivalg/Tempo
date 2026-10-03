import { apiRequest } from './client'

export interface PlanDef { id: string; plan_key: string; version: number; name: string; monthly_price_per_site_aud: number | null; entitlements: Record<string, boolean>; status: 'draft' | 'approved' | 'retired'; notes: string; created_by: string | null; approved_by: string | null; indicative: boolean }
export interface TenantRow { tenant_id: string; name: string; status: string; created_at: string; managed: boolean; plan: string | null; billing_source: string | null; manual_kind: string | null; subscription_status: string | null; licensed_sites: number | null; sites_in_use: number; worker_band: string | null; active_workers: number; allowance_state: 'ok' | 'near' | 'over' | null; expires_at: string | null }
export interface SubscriptionInput { plan_key: string; licensed_sites: number; worker_band: string; manual_kind: string; discount_pct: number; reason: string; reference?: string | null; expires_at?: string | null }
export interface SupportGrant { grant_id: string; operator_user_id: string; target_tenant_id: string; reason: string; site_ids: string[]; action_categories: string[]; approved_at: string; expires_at: string; terminated_at: string | null; state: 'live' | 'terminated' | 'expired' }
export interface AuditRow { event_id: string; at: string; actor_type: string; actor_id: string; tenant_id: string | null; action: string; decision: string; reason_code: string | null }

export const listPlans = () => apiRequest<PlanDef[]>('/platform/plans')
export const newPlanVersion = (body: { plan_key: string; name: string; monthly_price_per_site_aud: number | null; notes: string }) => apiRequest<PlanDef>('/platform/plans', { method: 'POST', body })
export const approvePlan = (id: string) => apiRequest<PlanDef>(`/platform/plans/${id}/approve`, { method: 'POST' })
export const tenantOverview = (q: string) => apiRequest<TenantRow[]>(`/platform/tenant-overview${q ? `?q=${encodeURIComponent(q)}` : ''}`)
export const createTenant = (body: { tenant_id: string; name: string; first_admin: { email: string }; initial_site_ids: string[]; subscription?: SubscriptionInput }) =>
  apiRequest<{ tenant_id: string; invite_path: string | null }>('/platform/tenants', { method: 'POST', body })
export const setSubscription = (tenant: string, body: SubscriptionInput) => apiRequest(`/platform/tenants/${tenant}/subscription`, { method: 'PUT', body: { billing_source: 'manual', ...body } })
export const setTenantStatus = (tenant: string, status: 'active' | 'suspended') => apiRequest(`/platform/tenants/${tenant}/status?status=${status}`, { method: 'POST' })
export const subscriptionHistory = (tenant: string) => apiRequest<{ at: string; actor: string; action: string; reason: string }[]>(`/platform/tenants/${tenant}/subscription-history`)
export const listGrants = () => apiRequest<SupportGrant[]>('/platform/support-grants')
export const createGrant = (body: { target_tenant_id: string; reason: string; hours: number; action_categories: string[]; site_ids: string[] }) => apiRequest<{ grant_id: string }>('/platform/support-grants', { method: 'POST', body })
export const endGrant = (id: string) => apiRequest(`/platform/support-grants/${id}/terminate`, { method: 'POST' })
export const platformAudit = () => apiRequest<AuditRow[]>('/platform/audit?limit=100')
export const addPlatformAdmin = (email: string) => apiRequest<{ user_id: string; invite_path: string | null }>('/platform/admins', { method: 'POST', body: { email } })
