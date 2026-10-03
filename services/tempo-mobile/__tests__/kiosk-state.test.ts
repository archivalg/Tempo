import { IDENTIFY, isSuccess, reduce, type KioskState } from '../src/kiosk/state'

const enter = (s: KioskState, worker: string, pin: string): KioskState => {
  for (const d of worker) s = reduce(s, { type: 'digit', d })
  s = reduce(s, { type: 'field', f: 'pin' })
  for (const d of pin) s = reduce(s, { type: 'digit', d })
  return s
}

describe('kiosk state machine', () => {
  it('collects a worker number and PIN, then offers only the actions the server allowed, in a fixed order', () => {
    let s = enter(IDENTIFY, '1001', '1234')
    expect(s).toMatchObject({ screen: 'identify', workerNo: '1001', pin: '1234' })
    s = reduce(s, { type: 'identified', identity: { mode: 'pin', workerNo: '1001', pin: '1234' }, masked: '•••001', state: 'working', actions: ['clock_out', 'break_start'] })
    expect(s).toMatchObject({ screen: 'choose', masked: '•••001', actions: ['break_start', 'clock_out'], stateLabel: 'You are clocked in.' })
  })

  it('shows success only from a server acknowledgement and says when it was a repeat', () => {
    const base = reduce(enter(IDENTIFY, '1', '1234'), { type: 'identified', identity: { mode: 'pin', workerNo: '1', pin: '1234' }, masked: 'x', state: 'not_clocked_in', actions: ['clock_in'] })
    const ok = reduce(base, { type: 'punch_result', action: 'clock_in', duplicate: false, at: '09:30' })
    expect(isSuccess(ok)).toBe(true)
    expect(ok).toMatchObject({ outcome: 'recorded', message: 'Clocked in at 09:30' })
    const dup = reduce(base, { type: 'punch_result', action: 'clock_in', duplicate: true, at: '09:30' })
    expect(dup).toMatchObject({ outcome: 'already_recorded' })
    expect((dup as { message: string }).message).toMatch(/Already recorded/)
  })

  it('never reports a lost connection or a refusal as success, and says NOT recorded', () => {
    const base = reduce(enter(IDENTIFY, '1', '1234'), { type: 'identified', identity: { mode: 'pin', workerNo: '1', pin: '1234' }, masked: 'x', state: 'working', actions: ['clock_out'] })
    const net = reduce(base, { type: 'punch_network_failed', action: 'clock_out' })
    expect(isSuccess(net)).toBe(false)
    expect(net).toMatchObject({ outcome: 'not_recorded' })
    expect((net as { message: string }).message).toMatch(/^NOT recorded/)
    const refused = reduce(base, { type: 'punch_refused', action: 'clock_out', message: 'Not clocked in.' })
    expect(isSuccess(refused)).toBe(false)
    expect((refused as { message: string }).message).toMatch(/^NOT recorded/)
  })

  it('clears the PIN after a failed identification and keeps a network failure distinct from a wrong PIN', () => {
    const typed = enter(IDENTIFY, '1001', '9999')
    const wrong = reduce(typed, { type: 'identify_failed', message: 'Not recognised.', kind: 'refused' })
    expect(wrong).toMatchObject({ pin: '', error: 'Not recognised.', field: 'pin' })
    const net = reduce(typed, { type: 'identify_failed', message: 'Cannot reach Tempo.', kind: 'network' })
    expect(net).toMatchObject({ pin: '', error: 'Cannot reach Tempo.' })
  })

  it('returns to a blank identification screen on reset: nothing about the previous employee survives', () => {
    const done = reduce(reduce(enter(IDENTIFY, '1001', '1234'), { type: 'identified', identity: { mode: 'pin', workerNo: '1001', pin: '1234' }, masked: 'x', state: 'working', actions: ['clock_out'] }), { type: 'punch_result', action: 'clock_out', duplicate: false, at: '17:00' })
    expect(reduce(done, { type: 'reset' })).toEqual(IDENTIFY)
    expect(JSON.stringify(reduce(done, { type: 'reset' }))).not.toMatch(/1001|1234/)
  })

  it('limits input lengths and supports backspace and clear', () => {
    let s = IDENTIFY
    for (let i = 0; i < 30; i++) s = reduce(s, { type: 'digit', d: '7' })
    expect((s as { workerNo: string }).workerNo.length).toBe(24)
    s = reduce(s, { type: 'backspace' })
    expect((s as { workerNo: string }).workerNo.length).toBe(23)
    expect(reduce(s, { type: 'clear' })).toMatchObject({ workerNo: '' })
  })
})
