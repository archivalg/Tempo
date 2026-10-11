import { apiFetch, newIdempotencyKey, randomUUID } from './client'
import type {
  ObjectiveProfile,
  RunComparisonResponse,
  RunCreateResponse,
  RunDetail,
  RunListResponse,
  RunType,
  TempoContext,
} from './types'

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
  // order_fulfillment only: a committed run claims real worker/order capacity (Order.committed_units,
  // app.models.orders.WorkerCommitment) that a later run — order-driven OR a roster publish — must
  // not double-book. A draft (the default) commits nothing and may freely reuse the same capacity.
  committed?: boolean
  demandMode?: 'known_orders' | 'forecast_only' | 'hybrid'
  forecastBasis?: 'total' | 'additional'
}

export function createRun(context: TempoContext, input: NewRunInput): Promise<RunCreateResponse> {
  return apiFetch<RunCreateResponse>(`/optimisations/${input.runType}`, context, {
    method: 'POST',
    idempotencyKey: newIdempotencyKey(),
    body: {
      request_id: `req_${randomUUID().slice(0, 12)}`,
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
      ...(input.runType === 'order_fulfillment'
        ? { input: { committed: !!input.committed, demand_mode: input.demandMode ?? 'known_orders', ...(input.forecastBasis ? { forecast_basis: input.forecastBasis } : {}) } }
        : {}),
    },
  })
}

// Re-submits a completed draft order_fulfillment run's own stored request (RunDetail.request) with
// input.committed forced to true, so "commit this plan" needs no re-entry of scope/window/config.
// Capacity may have moved since the draft ran (another commitment, a worker change) — the new run is
// a fresh commit attempt against current state, not a guarantee the draft's exact allocation repeats.
export function recommitRun(context: TempoContext, runType: RunType, originalRequest: Record<string, unknown>): Promise<RunCreateResponse> {
  const input = (originalRequest.input as Record<string, unknown>) ?? {}
  return apiFetch<RunCreateResponse>(`/optimisations/${runType}`, context, {
    method: 'POST',
    idempotencyKey: newIdempotencyKey(),
    body: {
      ...originalRequest,
      request_id: `req_${randomUUID().slice(0, 12)}`,
      input: { ...input, committed: true },
    },
  })
}

export interface ReleaseCommitmentResponse {
  run_id: string
  released: { order_id: string; quantity: number }[]
  released_worker_commitments: { worker_id: string; start_at: string; end_at: string }[]
}
export function releaseCommitment(context: TempoContext, runId: string): Promise<ReleaseCommitmentResponse> {
  return apiFetch<ReleaseCommitmentResponse>(`/runs/${runId}/release-commitment`, context, { method: 'POST' })
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

export function compareRuns(context: TempoContext, runIds: string[]): Promise<RunComparisonResponse> {
  return apiFetch<RunComparisonResponse>('/run-comparisons', context, {
    method: 'POST',
    body: { run_ids: runIds },
  })
}
