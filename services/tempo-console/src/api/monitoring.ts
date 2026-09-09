import { apiFetch } from './client'
import type { DataReadiness, DriftSignal, ModelMonitoringMetrics, TempoContext } from './types'

export function getModelMonitoring(context: TempoContext): Promise<{ models: Record<string, ModelMonitoringMetrics> }> {
  return apiFetch('/monitoring/models', context)
}

export function runDriftCheck(context: TempoContext): Promise<{ drift_signals: DriftSignal[] }> {
  return apiFetch('/monitoring/models/drift-check', context, { method: 'POST' })
}

export function getDataReadiness(context: TempoContext, capability: string, siteId?: string): Promise<DataReadiness> {
  const params = new URLSearchParams({ capability })
  if (siteId) params.set('site_id', siteId)
  return apiFetch(`/data-readiness?${params.toString()}`, context)
}
