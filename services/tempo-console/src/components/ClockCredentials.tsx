import { useCallback, useEffect, useState } from 'react'
import { getClockCredentials, setClockPin, unlockClockCredential, type ClockCredential } from '../api/ops'
import { ApiError } from '../api/client'
import { Banner, Empty, Skeleton, Status } from './ui'

/** Who can use the kiosk at this site. PINs are set, never shown; a reset also clears a lockout. */
export function ClockCredentials({ siteId }: { siteId: string }) {
  const [rows, setRows] = useState<ClockCredential[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [pin, setPin] = useState('')
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => { getClockCredentials(siteId).then(setRows).catch((e) => setErr(e.message)) }, [siteId])
  useEffect(() => { setRows(null); load() }, [load])
  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null)
    try { await fn(); setEditing(null); setPin(''); load() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Failed') } finally { setBusy(false) }
  }
  return (
    <section className="tp-card">
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      {!rows ? <div className="tp-body"><Skeleton h={160} /></div> : rows.length === 0 ? <Empty title="No workers at this site">Import staff on the Data page first.</Empty> : (
        <div style={{ overflow: 'auto', maxHeight: 560 }}>
          <table className="tp-table">
            <thead><tr><th>Worker</th><th>Badge no.</th><th>Status</th><th>PIN</th><th /></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.worker_id}>
                <td>{r.label}</td><td className="tp-num">{r.badge_no ?? <span className="tp-muted">none — set one on the Data page</span>}</td>
                <td>{r.status === 'active' ? <Status tone="ok">Active</Status> : <Status tone="neutral">{r.status}</Status>}</td>
                <td>{r.locked ? <Status tone="bad">Locked</Status> : r.has_pin ? <Status tone="ok">Set</Status> : <Status tone="risk">Not set</Status>}</td>
                <td>{editing === r.worker_id ? (
                  <form className="tp-row" onSubmit={(e) => { e.preventDefault(); void act(() => setClockPin(r.worker_id, pin)) }}>
                    <input aria-label={`New PIN for ${r.label}`} inputMode="numeric" autoComplete="off" pattern="[0-9]{4,8}" placeholder="4–8 digits" value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, '').slice(0, 8))} style={{ width: 110 }} />
                    <button className="tp-btn primary" disabled={busy || pin.length < 4}>Save</button><button type="button" className="tp-btn" onClick={() => { setEditing(null); setPin('') }}>Cancel</button>
                  </form>
                ) : (
                  <span className="tp-row"><button className="tp-btn" onClick={() => { setEditing(r.worker_id); setPin('') }}>{r.has_pin ? 'Reset PIN' : 'Set PIN'}</button>
                    {r.locked && <button className="tp-btn" disabled={busy} onClick={() => void act(() => unlockClockCredential(r.worker_id))}>Unlock</button>}</span>)}</td>
              </tr>))}</tbody>
          </table>
        </div>)}
      <p className="tp-muted tp-body" style={{ fontSize: 12 }}>Workers clock in with their badge number and PIN. After repeated wrong PINs the credential locks for a short time; setting a new PIN or unlocking clears it. Deactivating a worker is done through the staff import.</p>
    </section>
  )
}
