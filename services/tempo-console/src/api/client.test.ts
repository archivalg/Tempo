import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiFetch, ApiError } from './client'
import type { TempoContext } from './types'

const context: TempoContext = {
  tenant_id: 'ten_test',
  site_ids: ['site_mel_01'],
  customer_ids: [],
  user_id: 'usr_test',
  roles: ['operations_manager'],
  purpose: 'labour.console',
  correlation_id: 'cor_test',
}

describe('apiFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends the X-Tempo-Context header as JSON and returns the parsed body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiFetch<{ ok: boolean }>('/runs', context)

    expect(result).toEqual({ ok: true })
    const [, init] = fetchMock.mock.calls[0]
    expect(JSON.parse(init.headers['X-Tempo-Context'])).toEqual(context)
  })

  it('includes the Idempotency-Key header when provided', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 202 }))
    vi.stubGlobal('fetch', fetchMock)

    await apiFetch('/actions', context, { method: 'POST', body: { a: 1 }, idempotencyKey: 'key-123' })

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['Idempotency-Key']).toBe('key-123')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.body).toBe(JSON.stringify({ a: 1 }))
  })

  it('throws ApiError with the problem-detail fields on a non-2xx response', async () => {
    const body = { detail: 'caller lacks labour.plan permission', error_code: 'TEMPO-AUTH-002' }
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 403 }))
    vi.stubGlobal('fetch', fetchMock)

    await expect(apiFetch('/optimisations/named_roster', context)).rejects.toMatchObject({
      status: 403,
      errorCode: 'TEMPO-AUTH-002',
      message: 'caller lacks labour.plan permission',
    })
  })

  it('ApiError is an instance of Error', () => {
    const err = new ApiError(404, 'not found', 'TEMPO-ACTION-005')
    expect(err).toBeInstanceOf(Error)
    expect(err.status).toBe(404)
    expect(err.errorCode).toBe('TEMPO-ACTION-005')
  })
})
