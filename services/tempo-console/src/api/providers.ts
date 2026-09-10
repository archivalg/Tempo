import { apiFetch } from './client'
import type { CertificationRecord, LabourProviderRecord, SuppliedWorker, TempoContext } from './types'

export function createProvider(context: TempoContext, name: string): Promise<LabourProviderRecord> {
  return apiFetch<LabourProviderRecord>('/providers', context, { method: 'POST', body: { name } })
}

export function listProviders(context: TempoContext): Promise<LabourProviderRecord[]> {
  return apiFetch<LabourProviderRecord[]>('/providers', context)
}

export function registerSuppliedWorker(
  context: TempoContext,
  providerId: string,
  body: { home_site: string; source_ref?: string },
): Promise<SuppliedWorker> {
  return apiFetch<SuppliedWorker>(`/providers/${providerId}/workers`, context, { method: 'POST', body })
}

export function listSuppliedWorkers(context: TempoContext, providerId: string): Promise<SuppliedWorker[]> {
  return apiFetch<SuppliedWorker[]>(`/providers/${providerId}/workers`, context)
}

export function addCertification(
  context: TempoContext,
  providerId: string,
  workerId: string,
  body: { skill_code: string; valid_from: string; valid_to?: string; level?: string; evidence_ref?: string },
): Promise<CertificationRecord> {
  return apiFetch<CertificationRecord>(`/providers/${providerId}/workers/${workerId}/certifications`, context, {
    method: 'POST',
    body,
  })
}
