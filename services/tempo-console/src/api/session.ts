import { apiRequest } from './client'

export interface Access {
  user_id: string
  platform_admin: boolean
  mfa_verified: boolean
  idp: string
  email?: string | null
  username?: string | null
  mfa_enabled?: boolean
  mfa_required?: boolean
  tenant_id: string | null
  roles: string[]
  permissions: string[]
  site_ids: string[]
  customer_ids: string[]
  provider_ids: string[]
}

export interface AuthConfig {
  methods?: string[]
  provider: 'dev-local' | 'oidc' | 'password' | 'unconfigured'
  production_authentication: boolean
  notice?: string | null
}

export interface DevIdentity {
  subject: string
  email: string
  display_name: string | null
}

export const getAccess = () => apiRequest<Access>('/me/access')
export const getAuthConfig = () => apiRequest<AuthConfig>('/auth/config')
export const listDevIdentities = () => apiRequest<DevIdentity[]>('/auth/dev-identities')
export const devLogin = (subject: string, email: string, mfa: boolean) =>
  apiRequest<{ idp: string }>('/auth/dev-login', { method: 'POST', body: { subject, email, mfa } })
export const logout = () => apiRequest<{ status: string }>('/auth/logout', { method: 'POST' })

export type LoginResult = { status: 'signed_in'; mfa_enrol_required: boolean } | { status: 'mfa_required'; challenge: string }
export const passwordLogin = (username: string, password: string) => apiRequest<LoginResult>('/auth/login', { method: 'POST', body: { username, password } })
export const mfaVerify = (challenge: string, code: string) => apiRequest<{ status: string }>('/auth/mfa/verify', { method: 'POST', body: { challenge, code } })
export const mfaEnroll = () => apiRequest<{ secret: string; otpauth_uri: string }>('/auth/mfa/enroll', { method: 'POST' })
export const mfaConfirm = (code: string) => apiRequest<{ status: string }>('/auth/mfa/confirm', { method: 'POST', body: { code } })
export const changePassword = (current_password: string, new_password: string) => apiRequest<{ status: string }>('/auth/password', { method: 'POST', body: { current_password, new_password } })
export const inviteInfo = (token: string) => apiRequest<{ email: string; username: string | null; purpose: string; expires_at: string; password_rules: { min_length: number } }>(`/auth/invite/${encodeURIComponent(token)}`)
export const acceptInvite = (token: string, password: string, username?: string) => apiRequest<{ status: string; username: string }>('/auth/accept-invite', { method: 'POST', body: { token, password, username: username || null } })

export interface AdminUser { emailed?: 'sent' | 'failed' | 'not_configured' | 'no_address' | null; user_id: string; email: string; username: string | null; display_name: string | null; roles: string[]; site_ids: string[]; customer_ids: string[]; membership: string; has_password: boolean; mfa_enabled: boolean; locked: boolean; is_self: boolean; invite_token?: string | null; invite_path?: string | null; note?: string }
export const listUsers = () => apiRequest<AdminUser[]>('/admin/users')
export const inviteUser = (body: { email: string; display_name?: string; roles: string[]; site_ids: string[]; customer_ids: string[] }) => apiRequest<AdminUser>('/admin/users', { method: 'POST', body })
export const userAction = (id: string, action: 'suspend' | 'reinstate' | 'reset-password' | 'reset-mfa' | 'unlock') => apiRequest<AdminUser>(`/admin/users/${id}/${action}`, { method: 'POST' })
export const setGrants = (id: string, body: { roles: string[]; site_ids: string[]; customer_ids: string[] }) => apiRequest<AdminUser>(`/admin/users/${id}/grants`, { method: 'PUT', body })
