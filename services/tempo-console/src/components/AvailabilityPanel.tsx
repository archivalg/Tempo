import { useCallback, useEffect, useState } from 'react'
import { addAvailability, getAvailability, removeAvailability, type AvailabilityEntry } from '../api/ops'
import { ApiError } from '../api/client'
import { Banner, Empty, Skeleton, Status } from './ui'
import { fmtTime } from '../lib/format'
import { zonedToUtcIso } from '../lib/zoned'

const LABEL = { unavailable: 'Unavailable', leave: 'Leave', rdo: 'Rostered day off' } as const

/** Times a worker cannot be rostered. The board treats a shift over one as a hard conflict that blocks publication. */
export function AvailabilityPanel({ siteId, tz, start, workers, canEdit }: { siteId: string; tz: string; start: string; workers: { worker_id: string; label: string }[]; canEdit: boolean }) {
  const [rows, setRows] = useState<AvailabilityEntry[] | null>(null)
  const [f, setF] = useState({ worker: '', kind: 'leave', start: '', end: '' })
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => { getAvailability(siteId, start, 14).then(setRows).catch((e) => setErr(e.message)) }, [siteId, start])
  useEffect(() => { setRows(null); load() }, [load])
  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null)
    try { await fn(); load() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Failed') } finally { setBusy(false) }
  }
  return (
    <div className="tp-stack">
      <p className="tp-muted">Showing the fortnight from {start}. Entries that came from another system are read-only here.</p>
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      {!rows ? <Skeleton h={80} /> : rows.length === 0 ? <Empty title="No unavailability or leave in this period" /> : (
        <table className="tp-table"><thead><tr><th>Worker</th><th>Kind</th><th>From</th><th>To</th><th /></tr></thead>
          <tbody>{rows.map((a) => (
            <tr key={a.id}><td>{a.label}</td><td><Status tone={a.status === 'leave' ? 'neutral' : 'risk'}>{LABEL[a.status]}</Status></td>
              <td>{fmtTime(a.start_at, tz, { weekday: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })}</td>
              <td>{fmtTime(a.end_at, tz, { weekday: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })}</td>
              <td>{canEdit && a.editable ? <button className="tp-btn" disabled={busy} aria-label={`Remove ${LABEL[a.status]} for ${a.label}`} onClick={() => void act(() => removeAvailability(a.id))}>Remove</button> : <span className="tp-muted">{a.source}</span>}</td></tr>))}</tbody></table>)}
      {canEdit && (
        <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void act(async () => { await addAvailability(siteId, { worker_id: f.worker, status: f.kind, start_at: zonedToUtcIso(f.start, tz), end_at: zonedToUtcIso(f.end, tz) }); setF({ ...f, start: '', end: '' }) }) }}>
          <h3 style={{ margin: '8px 0 0', fontSize: 14 }}>Add an entry</h3>
          <label className="tp-field">Worker<select value={f.worker} onChange={(e) => setF({ ...f, worker: e.target.value })} required><option value="">Choose…</option>{workers.map((w) => <option key={w.worker_id} value={w.worker_id}>{w.label}</option>)}</select></label>
          <label className="tp-field">Kind<select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="leave">Leave</option><option value="unavailable">Unavailable</option><option value="rdo">Rostered day off</option></select></label>
          <div className="tp-cols2"><label className="tp-field">From ({tz})<input type="datetime-local" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} required /></label>
            <label className="tp-field">To ({tz})<input type="datetime-local" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} required /></label></div>
          <button className="tp-btn primary" disabled={busy || !f.worker || !f.start || !f.end}>Add</button>
        </form>)}
    </div>
  )
}
