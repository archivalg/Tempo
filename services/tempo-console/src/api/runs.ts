import { apiFetch, newIdempotencyKey } from './client'
import type { ObjectiveProfile, RunCreateResponse, RunDetail, RunListResponse, RunType, TempoContext } from './types'

export interface NewRunInput {
  runType: RunType
  siteIds: string[]
  customerIds: string[]
  windowStart: string
  windowEnd: string
  timezone: string
  bucketMinutes: number
  objectiveProfile: ObjectiveProfile
  policyVersion?: string
}

export function createRun(context: TempoContext, input: NewRunInput): Promise<RunCreateResponse> {
  return apiFetch<RunCreateResponse>(`/optimisations/${input.runType}`, context, {
    method: 'POST',
    idempotencyKey: newIdempotencyKey(),
    body: {
      request_id: `req_${crypto.randomUUID().slice(0, 12)}`,
      scope: { tenant_id: context.tenant_id, site_ids: input.siteIds, customer_ids: input.customerIds },
      planning_window: {
        start: input.windowStart,
        end: input.windowEnd,
        timezone: input.timezone,
        bucket_minutes: input.bucketMinutes,
      },
      configuration: {
        objective_profile: input.objectiveProfile,
        ...(input.policyVersion ? { policy_version: input.policyVersion } : {}),
      },
    },
  })
}

export function listRuns(
  context: TempoContext,
  filters: { runType?: string; status?: string; cursor?: string } = {},
): Promise<RunListResponse> {
  const params = new URLSearchParams()
  if (filters.runType) params.set('run_type', filters.runType)
  if (filters.status) params.set('status', filters.status)
  if (filters.cursor) params.set('cursor', filters.cursor)
  const query = params.toString()
  return apiFetch<RunListResponse>(`/runs${query ? `?${query}` : ''}`, context)
}

export function getRun(context: TempoContext, runId: string): Promise<RunDetail> {
  return apiFetch<RunDetail>(`/runs/${runId}`, context)
}

export function cancelRun(context: TempoContext, runId: string): Promise<{ run_id: string; status: string }> {
  return apiFetch(`/runs/${runId}/cancel`, context, { method: 'POST' })
}
