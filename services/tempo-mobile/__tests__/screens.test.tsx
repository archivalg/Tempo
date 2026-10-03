jest.mock('expo-secure-store', () => require('../test-support/helpers').secureStoreMock)
jest.mock('expo-constants', () => ({ __esModule: true, default: { expoConfig: { version: '0.1.0', extra: { appEnv: 'test', apiUrl: 'https://api.example.test/v1' } } } }))
jest.mock('expo-router', () => ({ useRouter: () => ({ push: jest.fn(), replace: jest.fn() }), useLocalSearchParams: () => ({}), Redirect: () => null }))
jest.mock('@react-native-community/netinfo', () => ({ __esModule: true, default: { addEventListener: (cb: (s: unknown) => void) => { (global as unknown as { __netCb: unknown }).__netCb = cb; return () => undefined } } }))
jest.mock('../src/push/register', () => ({ unregisterPush: jest.fn(), enablePush: jest.fn(), pushPermission: jest.fn(async () => 'undetermined') }))
jest.mock('../src/api/endpoints')

import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react-native'
import * as ep from '../src/api/endpoints'
import { ApiError } from '../src/api/client'
import { useResource } from '../src/hooks/useResource'
import { NetworkProvider } from '../src/net/network'
import { SessionProvider } from '../src/auth/session'
import Shifts from '../app/(app)/shifts'
import Offers from '../app/(app)/offers'

const m = ep as jest.Mocked<typeof ep>
const PROFILE = { user_id: 'u', worker_id: 'w', display_name: 'Eva', company: 'Acme', tenant_id: 't', site: { site_id: 's', name: 'Melbourne DC', timezone: 'Australia/Melbourne' }, employment_type: 'casual', server_time: '' }
const wrap = async (ui: React.ReactElement) => await render(<SessionProvider><NetworkProvider>{ui}</NetworkProvider></SessionProvider>)
const shift = (over = {}) => ({ id: 's1', site_id: 's', site_name: 'Melbourne DC', timezone: 'Australia/Melbourne', role: 'picker', zone: 'dock 2', start_at: '2099-10-05T20:00:00Z', end_at: '2099-10-06T04:00:00Z', start_local: '', end_local: '', local_date: '2099-10-06', overnight: false, duration_minutes: 480, dst_change_during_shift: false, break_minutes: 30, instructions: null, status: 'scheduled', ...over })

beforeEach(() => { jest.resetAllMocks(); m.getProfile.mockResolvedValue(PROFILE as never); m.getChanges.mockResolvedValue({ unseen: 0, changes: [] }) })

describe('screens: loading, empty, error and connection loss', () => {
  it('shows a loading state, then the empty state that explains drafts are hidden', async () => {
    let release!: (v: { as_of: string; timezone: string; shifts: never[] }) => void
    m.getShifts.mockReturnValue(new Promise((r) => { release = r }))
    await wrap(<Shifts />)
    expect(screen.getByText('Loading…')).toBeTruthy()
    await act(async () => { release({ as_of: '', timezone: 'Australia/Melbourne', shifts: [] }) })
    expect(await screen.findByText('No upcoming shifts')).toBeTruthy()
    expect(screen.getByText(/still a draft/)).toBeTruthy()
  })

  it('lists published shifts with times in the site zone', async () => {
    m.getShifts.mockResolvedValue({ as_of: '', timezone: 'Australia/Melbourne', shifts: [shift()] as never })
    await wrap(<Shifts />)
    expect(await screen.findByText('07:00 – 15:00')).toBeTruthy()          // 20:00Z in Melbourne
    expect(screen.getByText(/picker · dock 2/)).toBeTruthy()
    expect(screen.getByText(/30 min break/)).toBeTruthy()
  })

  it('shows an error with Try again, and recovers', async () => {
    m.getShifts.mockRejectedValueOnce(new ApiError('server', 'Tempo had a problem.')).mockResolvedValueOnce({ as_of: '', timezone: 'UTC', shifts: [] })
    await wrap(<Shifts />)
    expect(await screen.findByText('Tempo had a problem.')).toBeTruthy()
    await fireEvent.press(screen.getByText('Try again'))
    expect(await screen.findByText('No upcoming shifts')).toBeTruthy()
  })

  it('keeps the last good data and says so when a refresh fails because the connection dropped', async () => {
    const calls = jest.fn<Promise<string[]>, []>()
    calls.mockResolvedValueOnce(['a', 'b']).mockRejectedValueOnce(new ApiError('network', 'No connection to Tempo.'))
    const { result } = await renderHook(() => useResource(() => calls(), []))
    await waitFor(() => expect(result.current.data).toEqual(['a', 'b']))
    await act(async () => { result.current.refresh() })
    await waitFor(() => expect(result.current.error).toBe('No connection to Tempo.'))
    expect(result.current.data).toEqual(['a', 'b'])                         // what you had is still there
    expect(result.current.offline).toBe(true)
  })

  it('shows a "No connection" banner when the phone goes offline', async () => {
    m.getShifts.mockResolvedValue({ as_of: '', timezone: 'UTC', shifts: [] })
    await wrap(<Shifts />)
    await screen.findByText('No upcoming shifts')
    await act(async () => { (global as unknown as { __netCb: (s: unknown) => void }).__netCb({ isConnected: false, isInternetReachable: false }) })
    expect(await screen.findByText(/No connection/)).toBeTruthy()
    expect(screen.getByText(/will not be saved until you are back online/)).toBeTruthy()
  })
})

describe('offers screen', () => {
  const offer = (over = {}) => ({ id: 'o1', site_name: 'Melbourne DC', timezone: 'Australia/Melbourne', role: 'picker', zone: 'z', start_at: '2099-10-05T20:00:00Z', end_at: '2099-10-06T04:00:00Z', start_local: '2099-10-06T07:00:00+11:00', end_local: '2099-10-06T15:00:00+11:00', break_minutes: 30, instructions: 'Dock 2', expires_at: null, status: 'open', status_for_me: 'open', my_response: 'pending', ...over })

  it('accepting says it waits for the manager, and a server refusal is shown in plain words', async () => {
    m.getOffers.mockResolvedValue({ offers: [offer()] as never })
    m.respondOffer.mockRejectedValueOnce(new ApiError('conflict', 'this shift has already been taken', 422))
    await wrap(<Offers />)
    await fireEvent.press(await screen.findByText('Accept this shift'))
    expect(await screen.findByText(/this shift has already been taken/)).toBeTruthy()
    expect(m.respondOffer).toHaveBeenCalledWith('o1', 'accept')
  })

  it('shows the status of an offer someone else took, with no buttons', async () => {
    m.getOffers.mockResolvedValue({ offers: [offer({ status_for_me: 'taken' })] as never })
    await wrap(<Offers />)
    expect(await screen.findByText(/Taken by someone else/)).toBeTruthy()
    expect(screen.queryByText('Accept this shift')).toBeNull()
  })

  it('an accepted offer is clearly "waiting for your manager" and can be withdrawn', async () => {
    m.getOffers.mockResolvedValue({ offers: [offer({ status: 'pending_confirmation', status_for_me: 'accepted', my_response: 'accepted' })] as never })
    await wrap(<Offers />)
    expect(await screen.findByText(/waiting for your manager/)).toBeTruthy()
    expect(screen.getByText('Withdraw')).toBeTruthy()
  })
})
