import { useCallback, useEffect, useRef, useState } from 'react'
import { BASE_URL } from '../api/client'

// A kiosk authenticates as an enrolled DEVICE (credential kept in this browser's storage, bound server-side to one
// tenant and a fixed set of sites). Worker number + PIN says who is standing here; it can never change the device's scope.
const KEY = 'tempo.kiosk.device'
type Screen = 'enrol' | 'idle' | 'confirm' | 'done' | 'offline'
interface Who { worker_id: string; masked_identity: string; has_open_session: boolean; upcoming_shifts: { shift_id: string; role: string; zone: string; start_at: string; end_at: string }[] }

async function call<T>(path: string, cred: string | null, body: unknown): Promise<{ ok: boolean; status: number; data: T & { detail?: string } }> {
  const r = await fetch(`${BASE_URL}${path}`, { method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json', ...(cred ? { Authorization: `Bearer ${cred}` } : {}) }, body: JSON.stringify(body) })
  const t = await r.text()
  return { ok: r.ok, status: r.status, data: t ? JSON.parse(t) : ({} as never) }
}

export function KioskPage() {
  const [cred, setCred] = useState<string | null>(() => { try { return localStorage.getItem(KEY) } catch { return null } })
  const [screen, setScreen] = useState<Screen>(cred ? 'idle' : 'enrol')
  const [field, setField] = useState<'worker' | 'pin'>('worker')
  const [worker, setWorker] = useState('')
  const [pin, setPin] = useState('')
  const [code, setCode] = useState('')
  const [who, setWho] = useState<Who | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef<number | undefined>(undefined)

  const reset = useCallback(() => { setWorker(''); setPin(''); setWho(null); setField('worker'); setScreen('idle'); setMsg(null) }, [])
  // Safe timeout: never leave a verified identity or a half-typed PIN on screen.
  useEffect(() => {
    window.clearTimeout(timer.current)
    if (screen === 'confirm') timer.current = window.setTimeout(reset, 20000)
    if (screen === 'done') timer.current = window.setTimeout(reset, 5000)
    if (screen === 'idle' && (worker || pin)) timer.current = window.setTimeout(reset, 30000)
    return () => window.clearTimeout(timer.current)
  }, [screen, worker, pin, reset])

  const press = (d: string) => { setMsg(null); (field === 'worker' ? setWorker : setPin)((v) => (v + d).slice(0, field === 'worker' ? 24 : 12)) }
  const back = () => (field === 'worker' ? setWorker : setPin)((v) => v.slice(0, -1))

  async function enrol() {
    setBusy(true); setMsg(null)
    try {
      const r = await call<{ device_credential: string }>('/kiosk/enrol', null, { enrolment_code: code.trim() })
      if (!r.ok) { setMsg('That code is not valid. Ask an administrator for a new one.'); return }
      localStorage.setItem(KEY, r.data.device_credential); setCred(r.data.device_credential); setCode(''); setScreen('idle')
    } catch { setMsg('Cannot reach Tempo.') } finally { setBusy(false) }
  }
  async function verify() {
    if (!worker || !pin) return
    setBusy(true); setMsg(null)
    try {
      const r = await call<Who>('/attendance/whoami', cred, { method: 'pin', worker_no: worker, pin })
      if (r.status === 401 && !r.data.upcoming_shifts) { setMsg('Not recognised. Check your worker number and PIN.'); setPin(''); setField('pin'); return }
      if (r.status === 403) { setMsg('Locked for now. Please see a supervisor.'); reset(); return }
      if (!r.ok) { setMsg('Something went wrong. See a supervisor.'); return }
      setWho(r.data); setScreen('confirm')
    } catch { setScreen('offline') } finally { setBusy(false) }
  }
  async function punch(kind: 'clock-in' | 'clock-out') {
    setBusy(true); setMsg(null)
    try {
      const r = await call<{ clocked_in_at?: string; clocked_out_at?: string }>(`/attendance/${kind}`, cred, { method: 'pin', worker_no: worker, pin })
      if (!r.ok) { setMsg(r.data.detail ?? 'Could not record that. See a supervisor.'); return }
      const t = new Date(r.data.clocked_in_at ?? r.data.clocked_out_at ?? Date.now())
      setMsg(`${kind === 'clock-in' ? 'Clocked in' : 'Clocked out'} at ${t.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false })}`)
      setScreen('done'); setPin('')
    } catch { setScreen('offline') } finally { setBusy(false) }
  }

  const pad = ['1', '2', '3', '4', '5', '6', '7', '8', '9']
  return (
    <div className="tp-app" style={{ minHeight: '100vh', background: 'var(--tp-charcoal)', color: 'var(--tp-on-chrome)', display: 'grid', placeItems: 'center', padding: 16 }}>
      <main style={{ width: 'min(560px, 100%)' }} aria-live="polite">
        <img src="/brand/tempo-lockup-dark.png" alt="Tempo" style={{ height: 44, marginBottom: 12 }} />
        {screen === 'enrol' && (
          <div className="tp-card" style={{ padding: 24, color: 'var(--tp-ink)' }}>
            <h1 style={{ marginTop: 0 }}>Set up this kiosk</h1>
            <p className="tp-muted">An administrator creates the device in Administration and gives you a one-time code (valid 15 minutes).</p>
            <label className="tp-field">Enrolment code<input value={code} onChange={(e) => setCode(e.target.value)} autoFocus autoComplete="off" style={{ fontSize: 20 }} /></label>
            {msg && <p role="alert" style={{ color: 'var(--tp-red-ink)' }}>{msg}</p>}
            <button className="tp-btn primary" style={{ marginTop: 12, fontSize: 18, padding: '12px 20px' }} disabled={busy || code.length < 8} onClick={() => void enrol()}>Enrol device</button>
          </div>
        )}
        {screen === 'offline' && (
          <div className="tp-card" style={{ padding: 24, color: 'var(--tp-ink)' }}>
            <h1 style={{ marginTop: 0 }}>Cannot clock right now</h1>
            <p>Tempo can’t be reached and this kiosk does not store punches offline. Please tell your supervisor — they will record your time.</p>
            <button className="tp-btn primary" style={{ fontSize: 18, padding: '12px 20px' }} onClick={reset}>Try again</button>
          </div>
        )}
        {screen === 'idle' && (
          <div className="tp-card" style={{ padding: 20, color: 'var(--tp-ink)' }}>
            <h1 style={{ marginTop: 0, fontSize: 22 }}>Clock in or out</h1>
            <div className="tp-row" style={{ marginBottom: 12 }}>
              <button className="tp-btn" style={{ flex: 1, fontSize: 20, padding: 14, ...(field === 'worker' ? { outline: '3px solid var(--tp-focus)' } : {}) }} aria-pressed={field === 'worker'} onClick={() => setField('worker')}>Worker no.: <b className="tp-num">{worker || '—'}</b></button>
              <button className="tp-btn" style={{ flex: 1, fontSize: 20, padding: 14, ...(field === 'pin' ? { outline: '3px solid var(--tp-focus)' } : {}) }} aria-pressed={field === 'pin'} onClick={() => setField('pin')}>PIN: <b className="tp-num" aria-label={`${pin.length} digits entered`}>{'•'.repeat(pin.length) || '—'}</b></button>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
              {pad.map((d) => (<button key={d} className="tp-btn" style={{ fontSize: 28, padding: 18 }} onClick={() => press(d)}>{d}</button>))}
              <button className="tp-btn" style={{ fontSize: 18 }} onClick={() => (field === 'worker' ? setWorker('') : setPin(''))}>Clear</button>
              <button className="tp-btn" style={{ fontSize: 28, padding: 18 }} onClick={() => press('0')}>0</button>
              <button className="tp-btn" style={{ fontSize: 18 }} onClick={back} aria-label="Backspace">⌫</button>
            </div>
            {msg && <p role="alert" style={{ color: 'var(--tp-red-ink)', fontSize: 18 }}>{msg}</p>}
            <button className="tp-btn primary" style={{ width: '100%', marginTop: 12, fontSize: 22, padding: 16 }} disabled={busy || !worker || !pin} onClick={() => void verify()}>Continue</button>
          </div>
        )}
        {screen === 'confirm' && who && (
          <div className="tp-card" style={{ padding: 20, color: 'var(--tp-ink)' }}>
            <h1 style={{ marginTop: 0, fontSize: 22 }}>Hello, worker <span className="tp-num">{who.masked_identity}</span></h1>
            <p style={{ fontSize: 18 }}>{who.has_open_session ? 'You are clocked in.' : 'You are not clocked in.'}</p>
            <h2 style={{ fontSize: 15 }}>Your upcoming shifts</h2>
            {who.upcoming_shifts.length === 0 ? <p className="tp-muted">No upcoming shifts.</p> : <ul style={{ paddingLeft: 18 }}>{who.upcoming_shifts.slice(0, 4).map((s) => (<li key={s.shift_id} className="tp-num">{new Date(s.start_at).toLocaleString('en-AU', { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false })} – {new Date(s.end_at).toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit', hour12: false })} · {s.role}</li>))}</ul>}
            {msg && <p role="alert" style={{ color: 'var(--tp-red-ink)' }}>{msg}</p>}
            <div className="tp-row">
              {!who.has_open_session ? <button className="tp-btn primary" style={{ flex: 1, fontSize: 24, padding: 18 }} disabled={busy} onClick={() => void punch('clock-in')}>Clock in</button>
                : <button className="tp-btn primary" style={{ flex: 1, fontSize: 24, padding: 18 }} disabled={busy} onClick={() => void punch('clock-out')}>Clock out</button>}
              <button className="tp-btn" style={{ fontSize: 18, padding: 18 }} onClick={reset}>Cancel</button>
            </div>
          </div>
        )}
        {screen === 'done' && (
          <div className="tp-card" style={{ padding: 28, color: 'var(--tp-ink)', textAlign: 'center' }}>
            <div aria-hidden="true" style={{ fontSize: 48, color: 'var(--tp-green-ink)' }}>✓</div>
            <h1 style={{ fontSize: 26 }}>{msg}</h1>
            <p className="tp-muted">This screen clears automatically.</p>
          </div>
        )}
      </main>
    </div>
  )
}
