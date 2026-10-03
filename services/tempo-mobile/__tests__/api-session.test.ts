import { mem, secureStoreMock, json } from '../test-support/helpers'

jest.mock('expo-secure-store', () => require('../test-support/helpers').secureStoreMock)
jest.mock('expo-constants', () => ({ __esModule: true, default: { expoConfig: { version: '0.1.0', extra: { appEnv: 'test', apiUrl: 'https://api.example.test/v1' } } } }))

import { api, ApiError, refreshSession, setExpiredHandler } from '../src/api/client'
import * as store from '../src/auth/storage'

const fetchMock = jest.fn()
beforeEach(() => { secureStoreMock.setItemAsync.mockClear(); for (const k of Object.keys(mem)) delete mem[k]; fetchMock.mockReset(); (global as unknown as { fetch: unknown }).fetch = fetchMock; setExpiredHandler(() => undefined) })
const session = { access: 'A1', refresh: 'R1', accessExpiresAt: 'x', refreshExpiresAt: 'y' }

describe('API client', () => {
  it('sends the bearer token and returns the parsed body', async () => {
    await store.saveSession(session)
    fetchMock.mockResolvedValueOnce(json(200, { ok: 1 }))
    expect(await api('/me/profile')).toEqual({ ok: 1 })
    expect(fetchMock.mock.calls[0][0]).toBe('https://api.example.test/v1/me/profile')
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer A1')
  })

  it('refreshes once on 401, stores the rotated tokens, and retries the request', async () => {
    await store.saveSession(session)
    fetchMock.mockResolvedValueOnce(json(401, { detail: 'expired' }))
      .mockResolvedValueOnce(json(200, { access_token: 'A2', refresh_token: 'R2', expires_at: 'e', refresh_expires_at: 'f' }))
      .mockResolvedValueOnce(json(200, { shifts: [] }))
    expect(await api('/me/shifts')).toEqual({ shifts: [] })
    expect((await store.loadSession())?.refresh).toBe('R2')
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe('Bearer A2')
  })

  it('shares one refresh between simultaneous requests', async () => {
    await store.saveSession(session)
    fetchMock.mockImplementation(async (url: string, init: { headers: Record<string, string> }) => {
      if (String(url).endsWith('/mobile/auth/refresh')) return json(200, { access_token: 'A2', refresh_token: 'R2', expires_at: 'e', refresh_expires_at: 'f' })
      return init.headers.Authorization === 'Bearer A2' ? json(200, { ok: true }) : json(401, {})
    })
    await Promise.all([api('/me/shifts'), api('/me/offers'), api('/me/leave')])
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).endsWith('/mobile/auth/refresh')).length).toBe(1)
  })

  it('signs the person out and says so when the refresh token is dead', async () => {
    await store.saveSession(session)
    const expired = jest.fn()
    setExpiredHandler(expired)
    fetchMock.mockResolvedValueOnce(json(401, {})).mockResolvedValueOnce(json(401, { detail: 'revoked' }))
    await expect(api('/me/shifts')).rejects.toMatchObject({ kind: 'unauthorised' })
    expect(await store.loadSession()).toBeNull()
    expect(expired).toHaveBeenCalledTimes(1)
  })

  it('a lost connection is a network error, never a sign-out, and the stored session survives', async () => {
    await store.saveSession(session)
    const expired = jest.fn()
    setExpiredHandler(expired)
    fetchMock.mockResolvedValueOnce(json(401, {})).mockRejectedValueOnce(new TypeError('Network request failed'))
    await expect(api('/me/shifts')).rejects.toMatchObject({ kind: 'network' })
    expect(expired).not.toHaveBeenCalled()
    expect((await store.loadSession())?.refresh).toBe('R1')
    fetchMock.mockRejectedValueOnce(new TypeError('Network request failed'))
    await expect(api('/me/profile')).rejects.toBeInstanceOf(ApiError)
    expect(await refreshSession()).toBeDefined()
  })

  it('turns server answers into plain kinds and messages', async () => {
    await store.saveSession(session)
    fetchMock.mockResolvedValueOnce(json(422, { detail: 'this shift has already been taken' }))
    await expect(api('/me/offers/1/respond', { method: 'POST', body: {} })).rejects.toMatchObject({ kind: 'conflict', message: 'this shift has already been taken', status: 422 })
    fetchMock.mockResolvedValueOnce(json(500, {}))
    await expect(api('/me/shifts')).rejects.toMatchObject({ kind: 'server' })
    fetchMock.mockResolvedValueOnce(json(403, { detail: 'for employees' }))
    await expect(api('/me/shifts')).rejects.toMatchObject({ kind: 'forbidden' })
  })

  it('device (kiosk) calls use the device credential and never try to refresh an employee session', async () => {
    await store.saveSession(session)
    fetchMock.mockResolvedValueOnce(json(401, { detail: 'credential not recognised' }))
    await expect(api('/attendance/whoami', { method: 'POST', body: {}, deviceToken: 'tkd_x.y' })).rejects.toMatchObject({ kind: 'unauthorised' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer tkd_x.y')
    expect((await store.loadSession())?.access).toBe('A1')
  })

  it('keeps secrets only in the secure store', async () => {
    await store.saveSession(session)
    await store.saveKiosk({ credential: 'tkd_a.b', deviceId: 'd', siteIds: ['s'], tenantId: 't' })
    expect(secureStoreMock.setItemAsync).toHaveBeenCalledTimes(2)
    expect(secureStoreMock.setItemAsync.mock.calls.every((c) => c[2]?.keychainAccessible === 1)).toBe(true)
  })
})
