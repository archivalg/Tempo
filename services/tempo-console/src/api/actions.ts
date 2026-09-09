import { apiFetch, newIdempotencyKey } from './client'
import type {
  ActionDetail,
  ActionListResponse,
  ActionResponse,
  ActionTarget,
  ActionValidateResponse,
  TempoContext,
} from './types'

export interface ActionRequestBody {
  action_type: string
  recommendation_id: string
  target: ActionTarget
  expected_source_version: string | null
}

export function validateAction(context: TempoContext, body: ActionRequestBody): Promise<ActionValidateResponse> {
  return apiFetch<ActionValidateResponse>('/actions/validate', context, { method: 'POST', body })
}

export function executeAction(
  context: TempoContext,
  body: ActionRequestBody & { action_id: string; action_token: string },
): Promise<ActionResponse> {
  return apiFetch<ActionResponse>('/actions', context, { method: 'POST', body, idempotencyKey: newIdempotencyKey() })
}

export function reconcileAction(context: TempoContext, actionId: string): Promise<ActionResponse> {
  return apiFetch<ActionResponse>(`/actions/${actionId}/reconcile`, context, { method: 'POST' })
}

export function getAction(context: TempoContext, actionId: string): Promise<ActionDetail> {
  return apiFetch<ActionDetail>(`/actions/${actionId}`, context)
}

export function listActions(context: TempoContext, filters: { status?: string; cursor?: string } = {}): Promise<ActionListResponse> {
  const params = new URLSearchParams()
  if (filters.status) params.set('status', filters.status)
  if (filters.cursor) params.set('cursor', filters.cursor)
  const query = params.toString()
  return apiFetch<ActionListResponse>(`/actions${query ? `?${query}` : ''}`, context)
}
