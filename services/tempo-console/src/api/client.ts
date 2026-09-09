import type { TempoContext } from './types'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/v1'

export class ApiError extends Error {
  status: number
  errorCode?: string
  constructor(status: number, message: string, errorCode?: string) {
    super(message)
    this.status = status
    this.errorCode = errorCode
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST'
  body?: unknown
  idempotencyKey?: string
}

export async function apiFetch<T>(path: string, context: TempoContext, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {
    'X-Tempo-Context': JSON.stringify(context),
  }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json'
  if (options.idempotencyKey) headers['Idempotency-Key'] = options.idempotencyKey

  const response = await fetch(`${BASE_URL}${path}`, {
    method: options.method ?? 'GET',
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })

  const text = await response.text()
  const parsed = text ? JSON.parse(text) : undefined

  if (!response.ok) {
    const detail = parsed?.detail ?? parsed?.title ?? `request failed with status ${response.status}`
    throw new ApiError(response.status, detail, parsed?.error_code)
  }
  return parsed as T
}

// §8.1: "Idempotency-Key required for run creation and actions" — the
// console generates one per user-initiated mutation, never reuses one
// across distinct clicks.
export function newIdempotencyKey(): string {
  return crypto.randomUUID()
}
