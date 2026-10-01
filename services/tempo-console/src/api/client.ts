import type { TempoContext } from './types'

// Cross-origin in dev (console :5174 → API :8017) and same-origin behind nginx in the container build.
export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8017/v1'

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
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE' | 'PUT'
  body?: unknown
  idempotencyKey?: string
}

/** CSRF token cookie (double submit). Readable by design; it is not a credential on its own. */
function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)tempo_csrf=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : ''
}

let refreshing: Promise<boolean> | null = null

/** Rotates the refresh session once, even if several requests hit an expired access token together. */
function refreshSession(): Promise<boolean> {
  refreshing ??= fetch(`${BASE_URL}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'X-CSRF-Token': csrfToken() },
  })
    .then((r) => r.ok)
    .catch(() => false)
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

async function send(path: string, options: RequestOptions, headers: Record<string, string>) {
  const method = options.method ?? 'GET'
  const h = { ...headers }
  if (options.body !== undefined) h['Content-Type'] = 'application/json'
  if (options.idempotencyKey) h['Idempotency-Key'] = options.idempotencyKey
  if (method !== 'GET') h['X-CSRF-Token'] = csrfToken()
  return fetch(`${BASE_URL}${path}`, {
    method,
    headers: h,
    credentials: 'include',
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
  })
}

/**
 * Identity is the HttpOnly session cookie — never a header this code builds. The second parameter is
 * the legacy `TempoContext` the pre-Gate-1 pages still pass; it is ignored (kept so those call sites compile).
 */
export async function apiFetch<T>(path: string, _legacyContext: TempoContext | null | undefined, options: RequestOptions = {}): Promise<T> {
  return apiRequest<T>(path, options)
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}, extraHeaders: Record<string, string> = {}): Promise<T> {
  let response = await send(path, options, extraHeaders)
  if (response.status === 401 && !path.startsWith('/auth/') && (await refreshSession())) {
    response = await send(path, options, extraHeaders)
  }
  const text = await response.text()
  const parsed = text ? JSON.parse(text) : undefined
  if (!response.ok) {
    const detail = typeof parsed?.detail === 'string' ? parsed.detail : (parsed?.title ?? `request failed with status ${response.status}`)
    throw new ApiError(response.status, detail, parsed?.error_code)
  }
  return parsed as T
}

// §8.1: "Idempotency-Key required for run creation and actions" — one per user-initiated mutation.
export function newIdempotencyKey(): string {
  return randomUUID()
}

// crypto.randomUUID exists only in secure contexts (HTTPS/localhost); fall back so plain HTTP works too.
export function randomUUID(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  const b = crypto.getRandomValues(new Uint8Array(16))
  b[6] = (b[6] & 0x0f) | 0x40
  b[8] = (b[8] & 0x3f) | 0x80
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('')
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`
}

/** Downloads a file response (CSV export) through the same cookie session; the browser saves it under the server's filename. */
export async function downloadFile(path: string): Promise<void> {
  let response = await send(path, {}, {})
  if (response.status === 401 && (await refreshSession())) response = await send(path, {}, {})
  if (!response.ok) {
    const parsed = await response.json().catch(() => undefined)
    throw new ApiError(response.status, typeof parsed?.detail === 'string' ? parsed.detail : `export failed with status ${response.status}`)
  }
  const name = /filename="([^"]+)"/.exec(response.headers.get('content-disposition') ?? '')?.[1] ?? 'tempo-export.csv'
  const url = URL.createObjectURL(await response.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** Sends raw bytes (a CSV file) with the same cookie session, CSRF header and automatic refresh as every other call. */
export async function apiUpload<T>(path: string, body: ArrayBuffer, contentType = 'text/csv'): Promise<T> {
  const go = () => fetch(`${BASE_URL}${path}`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': contentType, 'X-CSRF-Token': csrfToken() }, body })
  let response = await go()
  if (response.status === 401 && (await refreshSession())) response = await go()
  const text = await response.text()
  const parsed = text ? JSON.parse(text) : undefined
  if (!response.ok) throw new ApiError(response.status, typeof parsed?.detail === 'string' ? parsed.detail : `request failed with status ${response.status}`, parsed?.error_code)
  return parsed as T
}
