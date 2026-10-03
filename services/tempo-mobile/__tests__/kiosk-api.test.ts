jest.mock('expo-secure-store', () => require('../test-support/helpers').secureStoreMock)
jest.mock('expo-constants', () => ({ __esModule: true, default: { expoConfig: { version: '0.1.0', extra: { appEnv: 'test', apiUrl: 'https://api.example.test/v1' } } } }))
jest.mock('react-native', () => ({ Platform: { OS: 'ios' } }))
import { ApiError } from '../src/api/client'
import { describeFailure } from '../src/kiosk/api'

describe('kiosk failure wording', () => {
  it('a lost connection says the person was NOT clocked, not that their PIN was wrong', () => {
    const f = describeFailure(new ApiError('network', 'x'))
    expect(f.kind).toBe('network')
    expect(f.message).toMatch(/NOT been clocked/)
    expect(describeFailure(new ApiError('timeout', 'x')).kind).toBe('network')
  })
  it('a wrong PIN, a locked credential and a disabled device are three different messages', () => {
    expect(describeFailure(new ApiError('unauthorised', 'credential not recognised', 401)).message).toMatch(/Not recognised/)
    expect(describeFailure(new ApiError('forbidden', 'credential is temporarily locked; see a supervisor', 403)).message).toMatch(/Locked/)
    const d = describeFailure(new ApiError('unauthorised', 'invalid device credential', 401))
    expect(d.deviceRevoked).toBe(true)
    expect(d.message).toMatch(/disabled by a manager/)
  })
})
