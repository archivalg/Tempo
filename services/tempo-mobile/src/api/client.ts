import { API_URL } from '../config'
import * as store from '../auth/storage'

export type ErrorKind = 'network' | 'timeout' | 'unauthorised' | 'forbidden' | 'not_found' | 'conflict' | 'invalid' | 'server'

export class ApiError extends Error {
  kind: ErrorKind
  status: number
  constructor(kind: ErrorKind, message: string, status = 0) {
    super(message)
    this.kind = kind
    this.status = status
  }
}

const TIMEOUT_MS = 15000

type Listener = () => void
let onExpired: Listener = () => undefined
/** The session layer registers here so a dead refresh token signs the person out everywhere at once. */
export function setExpiredHandler(fn: Listener): void { onExpired = fn }

export type RefreshResult = 'ok' | 'dead' | 'offline'
let refreshing: Promise<RefreshResult> | null = null

async function rawFetch(path: string, init: RequestInit & { token?: string | null }): Promise<Response> {
  const ctl = new AbortController()
  const t = setTimeout(() => ctl.abort(), TIMEOUT_MS)
  try {
    const headers: Record<string, string> = { Accept: 'application/json', ...(init.headers as Record<string, string> | undefined) }
    if (init.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json'
    if (init.token) headers.Authorization = `Bearer ${init.token}`
    return await fetch(`${API_URL}${path}`, { ...init, headers, signal: ctl.signal })
  } catch (e) {
    throw new ApiError((e as Error).name === 'AbortError' ? 'timeout' : 'network', (e as Error).name === 'AbortError' ? 'Tempo did not answer in time.' : 'No connection to Tempo.')
  } finally {
    clearTimeout(t)
  }
}

function kindFor(status: number): ErrorKind {
  if (status === 401) return 'unauthorised'
  if (status === 403) return 'forbidden'
  if (status === 404) return 'not_found'
  if (status === 409 || status === 422) return 'conflict'
  if (status >= 400 && status < 500) return 'invalid'
  return 'server'
}

async function parse(res: Response): Promise<unknown> {
  const text = await res.text()
  try { return text ? JSON.parse(text) : undefined } catch { return undefined }
}

function messageOf(body: unknown, status: number): string {
  const b = body as { detail?: unknown; title?: string } | undefined
  if (typeof b?.detail === 'string') return b.detail
  if (Array.isArray(b?.detail)) return 'Some of the details are not valid.'
  return b?.title ?? `Request failed (${status}).`
}

/** Exchanges the refresh token for new tokens. One refresh at a time, however many requests hit an expired token together. */
export function refreshSession(): Promise<RefreshResult> {
  if (!refreshing) {
    refreshing = (async () => {
      const s = await store.loadSession()
      if (!s) return 'dead'
      try {
        const res = await rawFetch('/mobile/auth/refresh', { method: 'POST', body: JSON.stringify({ refresh_token: s.refresh }) })
        if (!res.ok) { await store.clearSession(); return 'dead' }
        const d = (await parse(res)) as { access_token: string; refresh_token: string; expires_at: string; refresh_expires_at: string }
        await store.saveSession({ access: d.access_token, refresh: d.refresh_token, accessExpiresAt: d.expires_at, refreshExpiresAt: d.refresh_expires_at })
        return 'ok'
      } catch {
        return 'offline'   // the network failed, not the session: keep the stored tokens and report a connection problem, never a sign-out
      } finally {
        refreshing = null
      }
    })()
  }
  return refreshing
}

export interface RequestOptions { method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'; body?: unknown; auth?: boolean; deviceToken?: string }

/** Every call to Tempo. Handles the bearer token, one automatic refresh, and turns failures into ApiError with a plain message. */
export async function api<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const send = async (token: string | null) => rawFetch(path, { method, body: opts.body === undefined ? undefined : JSON.stringify(opts.body), token })
  let token: string | null = opts.deviceToken ?? null
  if (!token && opts.auth !== false) token = (await store.loadSession())?.access ?? null
  let res = await send(token)
  if (res.status === 401 && opts.auth !== false && !opts.deviceToken) {
    const r = await refreshSession()
    if (r === 'offline') throw new ApiError('network', 'No connection to Tempo.')
    if (r === 'ok') res = await send((await store.loadSession())?.access ?? null)
    if (r === 'dead' || res.status === 401) { await store.clearSession(); onExpired(); throw new ApiError('unauthorised', 'Your session has ended. Please sign in again.', 401) }
  }
  const body = await parse(res)
  if (!res.ok) throw new ApiError(kindFor(res.status), messageOf(body, res.status), res.status)
  return body as T
}
