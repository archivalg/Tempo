import { apiFetch } from './client'
import type { Connection, ConnectorDescriptor, TempoContext, TenantScope } from './types'

export function listConnectors(context: TempoContext): Promise<ConnectorDescriptor[]> {
  return apiFetch<ConnectorDescriptor[]>('/connectors', context)
}

export function listTenantScopes(context: TempoContext): Promise<TenantScope[]> {
  return apiFetch<TenantScope[]>('/tenant-scopes', context)
}

export function createTenantScope(
  context: TempoContext,
  body: { site_id: string; company_id?: string; customer_id?: string },
): Promise<TenantScope> {
  return apiFetch<TenantScope>('/tenant-scopes', context, { method: 'POST', body })
}

export function listConnections(context: TempoContext): Promise<{ connections: Connection[] }> {
  return apiFetch<{ connections: Connection[] }>('/connections', context)
}

export function createConnection(
  context: TempoContext,
  body: { source_system: string; site_id: string; display_name?: string },
): Promise<Connection> {
  return apiFetch<Connection>('/connections', context, { method: 'POST', body })
}
