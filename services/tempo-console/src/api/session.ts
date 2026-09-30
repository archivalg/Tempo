import { apiRequest } from './client'

export interface Access {
  user_id: string
  platform_admin: boolean
  mfa_verified: boolean
  idp: string
  tenant_id: string | null
  roles: string[]
  permissions: string[]
  site_ids: string[]
  customer_ids: string[]
  provider_ids: string[]
}

export interface AuthConfig {
  provider: 'dev-local' | 'oidc' | 'unconfigured'
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
