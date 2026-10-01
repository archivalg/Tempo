import { useState } from 'react'
import { createOverride, revokeOverride, type Demand, type DemandOverride } from '../api/ops'
import { fmtTime } from '../lib/format'
import { zonedToUtcIso } from '../lib/zoned'
import { Status } from './ui'

const describe = (o: DemandOverride) => (o.mode === 'multiply' ? `${o.value >= 1 ? '+' : '−'}${Math.abs(Math.round((o.value - 1) * 100))}%` : `set to ${o.value.toLocaleString()} units/day`)
const tone = { active: 'risk', expired: 'neutral', revoked: 'neutral' } as const

/** Manual adjustments sit on top of the forecast: reason and expiry are required, the model's number is kept, revoking keeps the history. */
export function DemandOverrides({ site, tz, d, days, canPlan, onChanged }: { site: string; tz: string; d: Demand | null; days: string[]; canPlan: boolean; onChanged: () => void }) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [f, setF] = useState({ activity: '', start: days[0], end: days[days.length - 1], mode: 'multiply' as 'multiply' | 'set_units', value: '10', reason: '', expires: '' })
  const [revoking, setRevoking] = useState<{ id: string; reason: string } | null>(null)
  const set = (k: keyof typeof f, v: string) => setF((p) => ({ ...p, [k]: v }))
  const list = d?.overrides ?? []

  async function save() {
    setBusy(true); setErr(null)
    try {
      const n = Number(f.value)
      await createOverride(site, {
        activity: f.activity || null, start_date: f.start, end_date: f.end, mode: f.mode,
        value: f.mode === 'multiply' ? 1 + n / 100 : n, reason: f.reason, expires_at: zonedToUtcIso(`${f.expires}T23:59`, tz),
      })
      setOpen(false); setF((p) => ({ ...p, reason: '' })); onChanged()
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  async function revoke() {
    if (!revoking) return
    setBusy(true); setErr(null)
    try { await revokeOverride(revoking.id, revoking.reason); setRevoking(null); onChanged() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <section className="tp-card" aria-label="Demand overrides"><header><h2>Manual adjustments</h2>
      {canPlan && !open && <button className="tp-btn" onClick={() => { setOpen(true); setF((p) => ({ ...p, start: days[0], end: days[days.length - 1] })) }}>Adjust demand</button>}</header>
      <div className="tp-body">
        <p className="tp-muted" style={{ fontSize: 12.5, marginTop: 0 }}>{d?.overrides_note}</p>
        {err && <p role="alert" className="tp-badge bad" style={{ whiteSpace: "normal", display: "block" }}>✕ {err}</p>}
        {open && (
          <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void save() }} aria-label="New demand adjustment">
            <label className="tp-field">Activity<select value={f.activity} onChange={(e) => set('activity', e.target.value)}><option value="">All activities</option>{d?.activities.map((a) => <option key={a}>{a}</option>)}</select></label>
            <div className="tp-row"><label className="tp-field">From<input type="date" value={f.start} onChange={(e) => set('start', e.target.value)} required /></label>
              <label className="tp-field">To<input type="date" value={f.end} onChange={(e) => set('end', e.target.value)} required /></label></div>
            <div className="tp-row"><label className="tp-field">Change by<select value={f.mode} onChange={(e) => set('mode', e.target.value)}><option value="multiply">Percent of forecast</option><option value="set_units">Fixed units per day</option></select></label>
              <label className="tp-field">{f.mode === 'multiply' ? 'Percent (+/−)' : 'Units per day'}<input type="number" step="any" value={f.value} onChange={(e) => set('value', e.target.value)} required /></label></div>
            <label className="tp-field">Reason (shown to approvers)<textarea rows={2} value={f.reason} onChange={(e) => set('reason', e.target.value)} required placeholder="e.g. Customer promotion starts Tuesday" /></label>
            <label className="tp-field">Expires<input type="date" value={f.expires} onChange={(e) => set('expires', e.target.value)} required /></label>
            <div className="tp-row"><button className="tp-btn primary" disabled={busy} type="submit">{busy ? 'Saving…' : 'Save & re-run forecast'}</button><button className="tp-btn" type="button" onClick={() => setOpen(false)}>Cancel</button></div>
          </form>
        )}
        {list.length === 0 ? <p className="tp-muted">No adjustments this week. The forecast shown is the statistical model.</p> : (
          <ul className="tp-list" aria-label="Adjustments">{list.map((o) => (
            <li key={o.id} className="tp-item" style={{ gridTemplateColumns: '1fr', cursor: 'default' }}>
              <span><Status tone={tone[o.status]}>{o.status}</Status> <strong>{describe(o)}</strong> · {o.activity ?? 'all activities'} · {o.start_date} → {o.end_date}</span>
              <span className="s">{o.reason}<br />{o.origin} · expires {fmtTime(o.expires_at, tz, { day: '2-digit', month: 'short' })}{o.revoke_reason ? ` · revoked: ${o.revoke_reason}` : ''}</span>
              {canPlan && o.status === 'active' && (revoking?.id === o.id ? (
                <span className="tp-row"><input aria-label="Reason for revoking" className="tp-input" placeholder="Reason" value={revoking.reason} onChange={(e) => setRevoking({ id: o.id, reason: e.target.value })} />
                  <button className="tp-btn" disabled={busy || revoking.reason.trim().length < 5} onClick={() => void revoke()}>Confirm revoke</button><button className="tp-btn" onClick={() => setRevoking(null)}>Keep</button></span>
              ) : <span><button className="tp-btn" onClick={() => setRevoking({ id: o.id, reason: '' })}>Revoke</button></span>)}
            </li>))}</ul>
        )}
      </div>
    </section>
  )
}
