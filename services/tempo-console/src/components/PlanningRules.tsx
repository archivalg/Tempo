import { useEffect, useState } from 'react'
import { getPlanningRules, putPlanningRules, type PlanningRules as Rules, type ShiftDef } from '../api/ops'
import { ApiError } from '../api/client'
import { Banner, Skeleton, Status } from './ui'

const FIELDS: [keyof Omit<Rules, 'policy_version' | 'is_default' | 'defaults' | 'saved_at'>, string, number, number, number][] = [
  ['min_rest_hours', 'Minimum rest between shifts (hours)', 8, 16, 0.5],
  ['max_weekly_hours', 'Maximum scheduled hours per worker per week', 20, 60, 1],
  ['hours_per_worker_per_day', 'Standard shift length (hours)', 4, 12, 0.5],
  ['max_overtime_hours_per_worker_per_day', 'Overtime allowed per day (hours)', 0, 4, 0.5],
  ['max_consecutive_days', 'Most consecutive days worked', 1, 7, 1],
]

/** The limits rosters are generated and checked against. Saving makes a new dated version; breaking one is a hard conflict that blocks publication. */
export function PlanningRules({ canEdit }: { canEdit: boolean }) {
  const [r, setR] = useState<Rules | null>(null)
  const [f, setF] = useState<Record<string, number> | null>(null)
  const [cal, setCal] = useState<ShiftDef[]>([])
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { getPlanningRules().then((x) => { setR(x); setF(Object.fromEntries(FIELDS.map(([k]) => [k, x[k] as number]))); setCal(x.shift_calendar) }).catch((e) => setMsg({ tone: 'bad', text: e.message })) }, [])
  if (!f || !r) return msg ? <Banner tone="bad" title="Could not load the rules">{msg.text}</Banner> : <Skeleton h={200} />
  async function save() {
    setBusy(true); setMsg(null)
    try { const x = await putPlanningRules({ ...(f as unknown as Record<string, number>), shift_calendar: cal } as never); setR(x); setMsg({ tone: 'ok', text: 'Saved. Applies to rosters generated and checked from now on.' }) } catch (e) { setMsg({ tone: 'bad', text: e instanceof ApiError ? e.message : 'Could not save' }) } finally { setBusy(false) }
  }
  return (
    <div className="tp-stack">
      {r.is_default ? <Banner tone="info" title="Using Tempo’s defaults">Nothing has been saved for this organisation. Save to make these limits your own.</Banner> : <Status tone="ok">Saved version {r.policy_version}</Status>}
      <fieldset className="tp-stack" disabled={!canEdit} style={{ border: 0, padding: 0, margin: 0 }}>
        {FIELDS.map(([k, label, min, max, step]) => (
          <label key={k} className="tp-field">{label}
            <input type="number" min={min} max={max} step={step} value={f[k]} onChange={(e) => setF({ ...f, [k]: Number(e.target.value) })} />
            <span className="tp-muted" style={{ fontSize: 12 }}>Default {r.defaults[k]}; allowed {min}–{max}</span></label>))}
      </fieldset>
      <h3 style={{ margin: '8px 0 0', fontSize: 14 }}>Shifts {r.shift_calendar_is_default && <Status tone="neutral">Tempo default</Status>}</h3>
      <fieldset className="tp-stack" disabled={!canEdit} style={{ border: 0, padding: 0, margin: 0 }}>
        {cal.map((x, i) => (
          <div key={i} className="tp-row" role="group" aria-label={`Shift ${i + 1}`}>
            <label className="tp-field">Name<input value={x.code} maxLength={20} onChange={(e) => setCal(cal.map((y, j) => (j === i ? { ...y, code: e.target.value.replace(/[^A-Za-z0-9_-]/g, '') } : y)))} style={{ width: 110 }} /></label>
            <label className="tp-field">Starts (hour)<input type="number" min={0} max={23} value={x.start_hour} onChange={(e) => setCal(cal.map((y, j) => (j === i ? { ...y, start_hour: Number(e.target.value) } : y)))} style={{ width: 80 }} /></label>
            <label className="tp-field">Ends (hour)<input type="number" min={0} max={24} value={x.end_hour} onChange={(e) => setCal(cal.map((y, j) => (j === i ? { ...y, end_hour: Number(e.target.value) } : y)))} style={{ width: 80 }} /></label>
            {cal.length > 1 && <button type="button" className="tp-btn" aria-label={`Remove shift ${x.code}`} onClick={() => setCal(cal.filter((_, j) => j !== i))}>Remove</button>}
          </div>))}
        {cal.length < 8 && <button type="button" className="tp-btn" onClick={() => setCal([...cal, { code: `shift${cal.length + 1}`, start_hour: 6, end_hour: 14, share: null }])}>Add a shift</button>}
      </fieldset>
      <p className="tp-muted" style={{ fontSize: 12 }}>The generator fills each day from these shifts, splitting the day’s headcount evenly. A shift whose end is at or before its start runs overnight into the next day. Times are the site’s local clock.</p>
      {msg && <p role="status" style={{ color: msg.tone === 'bad' ? 'var(--tp-red-ink)' : undefined }}>{msg.text}</p>}
      {canEdit ? <button className="tp-btn primary" disabled={busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save rules'}</button> : <p className="tp-muted">Only a tenant administrator can change these.</p>}
      <p className="tp-muted" style={{ fontSize: 12 }}>The draft generator plans against rest, shift length, overtime and consecutive-day limits; the weekly maximum is checked when a roster is validated, so a draft that exceeds it is blocked from publication rather than silently trimmed. Earlier versions are kept.</p>
    </div>
  )
}
