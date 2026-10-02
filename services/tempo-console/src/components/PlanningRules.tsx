import { useEffect, useState } from 'react'
import { getPlanningRules, putPlanningRules, type PlanningRules as Rules } from '../api/ops'
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
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { getPlanningRules().then((x) => { setR(x); setF(Object.fromEntries(FIELDS.map(([k]) => [k, x[k]]))) }).catch((e) => setMsg({ tone: 'bad', text: e.message })) }, [])
  if (!f || !r) return msg ? <Banner tone="bad" title="Could not load the rules">{msg.text}</Banner> : <Skeleton h={200} />
  async function save() {
    setBusy(true); setMsg(null)
    try { const x = await putPlanningRules(f as never); setR(x); setMsg({ tone: 'ok', text: 'Saved. Applies to rosters generated and checked from now on.' }) } catch (e) { setMsg({ tone: 'bad', text: e instanceof ApiError ? e.message : 'Could not save' }) } finally { setBusy(false) }
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
      {msg && <p role="status" style={{ color: msg.tone === 'bad' ? 'var(--tp-red-ink)' : undefined }}>{msg.text}</p>}
      {canEdit ? <button className="tp-btn primary" disabled={busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save rules'}</button> : <p className="tp-muted">Only a tenant administrator can change these.</p>}
      <p className="tp-muted" style={{ fontSize: 12 }}>The draft generator plans against rest, shift length, overtime and consecutive-day limits; the weekly maximum is checked when a roster is validated, so a draft that exceeds it is blocked from publication rather than silently trimmed. Earlier versions are kept.</p>
    </div>
  )
}
