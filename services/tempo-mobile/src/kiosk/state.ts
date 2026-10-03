/**
 * The kiosk's screen logic as a pure state machine, so the rules that matter are testable without a device:
 *  - success is shown ONLY after the server acknowledged the clocking;
 *  - a lost connection is shown as "NOT recorded", never as success;
 *  - every result returns to the identification screen by itself, and everything about the employee is cleared on the way.
 */
export type KioskAction = 'clock_in' | 'break_start' | 'break_end' | 'clock_out'

export type Identity = { mode: 'pin'; workerNo: string; pin: string } | { mode: 'qr'; token: string }

export type KioskState =
  | { screen: 'identify'; workerNo: string; pin: string; field: 'worker' | 'pin'; error: string | null; busy: boolean }
  | { screen: 'choose'; identity: Identity; masked: string; actions: KioskAction[]; stateLabel: string; locationMode: string; error: string | null; busy: boolean }
  | { screen: 'result'; outcome: 'recorded' | 'already_recorded' | 'refused' | 'not_recorded'; action: KioskAction; message: string; at: string | null }

export const IDENTIFY: KioskState = { screen: 'identify', workerNo: '', pin: '', field: 'worker', error: null, busy: false }

export const RETURN_AFTER_MS = { result: 6000, choose: 20000, identify: 60000 }

export const ACTION_LABEL: Record<KioskAction, string> = { clock_in: 'Clock in', break_start: 'Start break', break_end: 'End break', clock_out: 'Clock out' }
const DONE: Record<KioskAction, string> = { clock_in: 'Clocked in', break_start: 'Break started', break_end: 'Back from break', clock_out: 'Clocked out' }

export type Event =
  | { type: 'digit'; d: string } | { type: 'backspace' } | { type: 'clear' } | { type: 'field'; f: 'worker' | 'pin' }
  | { type: 'busy' } | { type: 'identified'; identity: Identity; masked: string; state: string; actions: string[]; locationMode?: string }
  | { type: 'identify_failed'; message: string; kind: 'refused' | 'network' }
  | { type: 'punch_result'; action: KioskAction; duplicate: boolean; at: string | null }
  | { type: 'punch_refused'; action: KioskAction; message: string } | { type: 'punch_network_failed'; action: KioskAction }
  | { type: 'reset' }

const STATE_LABEL: Record<string, string> = { not_clocked_in: 'You are not clocked in.', working: 'You are clocked in.', on_break: 'You are on a break.' }
const ORDER: KioskAction[] = ['clock_in', 'break_start', 'break_end', 'clock_out']

export function reduce(s: KioskState, e: Event): KioskState {
  if (e.type === 'reset') return IDENTIFY
  switch (s.screen) {
    case 'identify':
      switch (e.type) {
        case 'digit': {
          const k = s.field === 'worker' ? 'workerNo' : 'pin'
          const max = k === 'workerNo' ? 24 : 12
          return { ...s, [k]: (s[k] + e.d).slice(0, max), error: null }
        }
        case 'backspace': { const k = s.field === 'worker' ? 'workerNo' : 'pin'; return { ...s, [k]: s[k].slice(0, -1) } }
        case 'clear': return { ...s, [s.field === 'worker' ? 'workerNo' : 'pin']: '' }
        case 'field': return { ...s, field: e.f }
        case 'busy': return { ...s, busy: true, error: null }
        case 'identified': return { screen: 'choose', identity: e.identity, masked: e.masked, actions: ORDER.filter((a) => e.actions.includes(a)), stateLabel: STATE_LABEL[e.state] ?? '', locationMode: e.locationMode ?? 'off', error: null, busy: false }
        case 'identify_failed':
          // the PIN is cleared on every failure; a network failure is never reported as a wrong PIN
          return { ...s, pin: '', field: e.kind === 'network' ? s.field : 'pin', busy: false, error: e.message }
        default: return s
      }
    case 'choose':
      switch (e.type) {
        case 'busy': return { ...s, busy: true, error: null }
        case 'punch_result': return { screen: 'result', outcome: e.duplicate ? 'already_recorded' : 'recorded', action: e.action, at: e.at, message: e.duplicate ? `Already recorded${e.at ? ` at ${e.at}` : ''}. Nothing more was needed.` : `${DONE[e.action]}${e.at ? ` at ${e.at}` : ''}` }
        case 'punch_refused': return { screen: 'result', outcome: 'refused', action: e.action, at: null, message: `NOT recorded. ${e.message}` }
        case 'punch_network_failed': return { screen: 'result', outcome: 'not_recorded', action: e.action, at: null, message: 'NOT recorded. Tempo could not be reached. Tell your supervisor, or try again.' }
        default: return s
      }
    default: return s
  }
}

export const isSuccess = (s: KioskState): boolean => s.screen === 'result' && (s.outcome === 'recorded' || s.outcome === 'already_recorded')
