import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { generateDraftRoster, getRoster, type RosterShift } from '../api/ops'
import { ApiError } from '../api/client'
import { useSite } from '../components/AppShell'
import { Banner, Drawer, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { fmtMoney, fmtNum, fmtTime, localDate } from '../lib/format'

const EMP: Record<string, string> = { permanent: 'PT', casual: 'CA', labour_hire: 'LH' }
const CONFLICT_LABEL: Record<string, string> = { overlap: 'Overlap', rest: 'Rest', availability: 'Availability', certification: 'Certification', site_eligibility: 'Site eligibility', max_hours: 'Max hours' }

/** UTC instant of local midnight for a YYYY-MM-DD date in `tz` (DST-safe). */
function localMidnightUtc(date: string, tz: string): string {
  const guess = new Date(`${date}T00:00:00Z`)
  const off = (d: Date) => { const p = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).formatToParts(d); const g = (t: string) => Number(p.find((x) => x.type === t)!.value); return Date.UTC(g('year'), g('month') - 1, g('day'), g('hour'), g('minute'), g('second')) - d.getTime() }
  return new Date(guess.getTime() - off(guess)).toISOString()
}
const addDays = (date: string, n: number) => { const d = new Date(`${date}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const mondayOf = (date: string) => { const d = new Date(`${date}T00:00:00Z`); return addDays(date, -((d.getUTCDay() + 6) % 7)) }

export default function RosterPlannerPage() {
  const { site } = useSite()
  const { access, can } = useTempoContext()
  const [params, setParams] = useSearchParams()
  const tz = site?.timezone ?? 'UTC'
  const start = params.get('start') ?? mondayOf(localDate(new Date(), tz))
  const view = (params.get('view') as 'published' | 'draft' | null) ?? undefined
  const [mode, setMode] = useState<'week' | 'day'>('week')
  const [dayIdx, setDayIdx] = useState(0)
  const [filter, setFilter] = useState('')
  const [zone, setZone] = useState('')
  const [nonce, setNonce] = useState(0)
  const [picked, setPicked] = useState<RosterShift | null>(null)
  const [gen, setGen] = useState<{ busy: boolean; error?: string }>({ busy: false })
  const q = useApi(() => (site ? getRoster(site.site_id, start, view) : Promise.resolve(null)), [site?.site_id, start, view, nonce])
  const ro = q.data
  const set = (k: string, v: string | null) => { const p = new URLSearchParams(params); if (v == null) p.delete(k); else p.set(k, v); setParams(p, { replace: true }) }

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(start, i)), [start])
  const workers = ro?.workers ?? []
  const byWorkerDay = useMemo(() => {
    const m = new Map<string, RosterShift[]>()
    for (const s of ro?.shifts ?? []) { const k = `${s.worker_id}|${localDate(new Date(s.start_at), tz)}`; m.set(k, [...(m.get(k) ?? []), s]) }
    return m
  }, [ro, tz])
  const shown = workers.filter((w) => (!filter || w.label.toLowerCase().includes(filter.toLowerCase()) || w.skills.some((s) => s.includes(filter.toLowerCase()))) &&
    (!zone || (ro?.shifts ?? []).some((s) => s.worker_id === w.worker_id && s.zone === zone)))
  const zones = useMemo(() => [...new Set((ro?.shifts ?? []).map((s) => s.zone))].sort(), [ro])
  const flagged = new Set((ro?.conflicts ?? []).map((c) => c.shift_id))

  async function generate() {
    if (!site || !access?.tenant_id) return
    setGen({ busy: true })
    try {
      await generateDraftRoster(access.tenant_id, site.site_id, access.customer_ids, localMidnightUtc(start, tz), 'ensemble_demo_v1')
      set('view', 'draft'); setNonce((n) => n + 1); setGen({ busy: false })
    } catch (e) { setGen({ busy: false, error: e instanceof ApiError ? e.message : 'Draft generation failed' }) }
  }

  if (!site) return <Empty title="No site available" />
  const t = ro?.totals
  const cur = ro ? (ro.view === 'draft' ? t!.draft : t!.published) : null
  const cmp = ro ? (ro.view === 'draft' ? t!.published : t!.draft) : null
  return (
    <>
      <PageHead title="Roster Planner" sub={<>{site.name} · week of {days[0]} · times in {tz}</>}>
        <div className="tp-seg" role="group" aria-label="Range"><button aria-pressed={mode === 'week'} onClick={() => setMode('week')}>Week</button><button aria-pressed={mode === 'day'} onClick={() => setMode('day')}>Day</button></div>
        <div className="tp-row" role="group" aria-label="Date navigator">
          <button className="tp-btn" onClick={() => set('start', addDays(start, -7))} aria-label="Previous week">←</button>
          <button className="tp-btn" onClick={() => set('start', null)}>This week</button>
          <button className="tp-btn" onClick={() => set('start', addDays(start, 7))} aria-label="Next week">→</button>
        </div>
        <div className="tp-seg" role="group" aria-label="Roster version">
          <button aria-pressed={ro?.view === 'published'} onClick={() => set('view', 'published')}>Published</button>
          <button aria-pressed={ro?.view === 'draft'} onClick={() => set('view', 'draft')} disabled={!ro?.has_draft}>Draft{ro?.has_draft ? '' : ' (none)'}</button>
        </div>
        {can('labour.plan') && <button className="tp-btn primary" disabled={gen.busy} onClick={() => void generate()}>{gen.busy ? 'Generating… (running solver)' : 'Generate draft roster'}</button>}
      </PageHead>
      {gen.error && <Banner tone="bad" title="Could not generate a draft">{gen.error}</Banner>}
      {ro && ro.site.operating_mode === 'overlay' && <Banner tone="info" title="Overlay site">The roster of record is in the external system. Tempo shows it read-only; publication back requires a vendor-specific approval gate that is not enabled.</Banner>}

      {ro && (
        <div className="tp-band" aria-label="Demand coverage by day">
          <div className="tp-muted" style={{ alignSelf: 'center', fontSize: 12 }}>Required vs rostered hours ({ro.view})</div>
          {ro.coverage_band.map((b) => (
            <div key={b.date} className="tp-day" style={{ borderColor: b.status === 'covered' ? 'var(--tp-green)' : b.status === 'risk' ? 'var(--tp-amber)' : b.status === 'shortage' ? 'var(--tp-red)' : 'var(--tp-line)', background: b.status === 'covered' ? 'var(--tp-green-bg)' : b.status === 'risk' ? 'var(--tp-amber-bg)' : b.status === 'shortage' ? 'var(--tp-red-bg)' : 'var(--tp-surface)', color: b.status === 'covered' ? 'var(--tp-green-ink)' : b.status === 'risk' ? 'var(--tp-amber-ink)' : b.status === 'shortage' ? 'var(--tp-red-ink)' : 'inherit' }}>
              <b>{fmtTime(`${b.date}T12:00:00Z`, 'UTC', { weekday: 'short', day: '2-digit' })}</b> <span aria-hidden="true">{b.status === 'covered' ? '✓' : b.status === 'risk' ? '▲' : b.status === 'shortage' ? '✕' : ''}</span>
              <div className="tp-num">{fmtNum(b.rostered_hours)} / {b.required_hours != null ? fmtNum(b.required_hours) : 'no forecast'} h</div>
              <div>{b.status === 'covered' ? 'Covered' : b.status === 'risk' ? 'At risk' : b.status === 'shortage' ? 'Shortage' : 'No verified demand'}</div>
            </div>
          ))}
        </div>
      )}

      <div className="tp-grid">
        <div className="tp-stack">
          <div className="tp-row">
            <label className="tp-field">Find worker or skill<input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="name, picker, forklift…" /></label>
            <label className="tp-field">Zone<select value={zone} onChange={(e) => setZone(e.target.value)}><option value="">All zones</option>{zones.map((z) => <option key={z}>{z}</option>)}</select></label>
            {mode === 'day' && <label className="tp-field">Day<select value={dayIdx} onChange={(e) => setDayIdx(Number(e.target.value))}>{days.map((d, i) => <option key={d} value={i}>{fmtTime(`${d}T12:00:00Z`, 'UTC', { weekday: 'long', day: '2-digit', month: 'short' })}</option>)}</select></label>}
            <span className="tp-muted">{shown.length} of {workers.length} workers</span>
          </div>
          {!ro ? <Skeleton h={360} /> : ro.shifts.length === 0 ? <Empty title={`No ${ro.view} roster for this week`}>{can('labour.plan') ? 'Use “Generate draft roster” to create one from the forecast.' : 'Nothing has been published.'}</Empty> : mode === 'week' ? (
            <div className="tp-board" role="region" aria-label="Roster board, scrollable" tabIndex={0}>
              <table>
                <caption className="tp-sr-only">Roster: workers by day. Each cell lists that worker's shifts.</caption>
                <thead><tr><th className="tp-w" scope="col">Worker</th>{days.map((d) => <th key={d} scope="col">{fmtTime(`${d}T12:00:00Z`, 'UTC', { weekday: 'short', day: '2-digit', month: 'short' })}</th>)}</tr></thead>
                <tbody>
                  {shown.map((w) => (
                    <tr key={w.worker_id}>
                      <th className="tp-w" scope="row"><div style={{ fontWeight: 600 }}>{w.label}<span className="tp-emp" title={w.employment_type}>{EMP[w.employment_type] ?? w.employment_type}</span></div><div className="tp-muted" style={{ fontSize: 11 }}>{w.skills.join(' · ')}</div></th>
                      {days.map((d) => (
                        <td key={d}>{(byWorkerDay.get(`${w.worker_id}|${d}`) ?? []).map((s) => (
                          <button key={s.shift_id} className={`tp-shift${ro.view === 'draft' ? ' draft' : ''}${flagged.has(s.shift_id) ? ' conflict' : ''}`} onClick={() => setPicked(s)}
                            aria-label={`${w.label}, ${s.role} in ${s.zone}, ${fmtTime(s.start_at, tz)} to ${fmtTime(s.end_at, tz)}${flagged.has(s.shift_id) ? ', has a hard conflict' : ''}`}>
                            <b>{fmtTime(s.start_at, tz)}–{fmtTime(s.end_at, tz)}</b> {flagged.has(s.shift_id) && <span aria-hidden="true">✕</span>}<br />{s.role} · {s.zone}
                          </button>))}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <DayTimeline ro={ro} day={days[dayIdx]} tz={tz} rows={shown} flagged={flagged} onPick={setPicked} />
          )}
          <div className="tp-muted" style={{ fontSize: 12 }}>PT permanent · CA casual · LH labour hire. Drag-and-drop editing and its keyboard alternative are not built yet; this increment is read, validate and generate.</div>
        </div>

        <aside className="tp-stack" aria-label="Insights">
          <section className="tp-card"><header><h2>{ro?.view === 'draft' ? 'Draft vs published' : 'Published roster'}</h2></header>
            <div className="tp-body">
              {!ro || !cur ? <Skeleton h={120} /> : (
                <table className="tp-table tp-num"><thead><tr><th></th><th>{ro.view === 'draft' ? 'Draft' : 'Published'}</th>{ro.has_draft && <th>{ro.view === 'draft' ? 'Published' : 'Draft'}</th>}</tr></thead>
                  <tbody>
                    <tr><td>Shifts</td><td>{cur.shifts}</td>{ro.has_draft && <td>{cmp!.shifts}</td>}</tr>
                    <tr><td>Workers</td><td>{cur.workers}</td>{ro.has_draft && <td>{cmp!.workers}</td>}</tr>
                    <tr><td>Hours</td><td>{fmtNum(cur.hours)}</td>{ro.has_draft && <td>{fmtNum(cmp!.hours)}</td>}</tr>
                    <tr><td>Agency share</td><td>{cur.agency_share_pct != null ? `${cur.agency_share_pct}%` : '—'}</td>{ro.has_draft && <td>{cmp!.agency_share_pct != null ? `${cmp!.agency_share_pct}%` : '—'}</td>}</tr>
                    {'cost' in cur && <tr><td>Cost</td><td>{cur.cost != null ? fmtMoney(cur.cost) : 'withheld'}</td>{ro.has_draft && <td>{cmp!.cost != null ? fmtMoney(cmp!.cost) : '—'}</td>}</tr>}
                  </tbody></table>
              )}
              {cur?.cost_note && <p className="tp-muted">{cur.cost_note}</p>}
            </div>
          </section>
          <section className="tp-card"><header><h2>Hard conflicts</h2>{ro && (ro.hard_conflicts === 0 ? <Status tone="ok">None</Status> : <Status tone="bad">{ro.hard_conflicts}</Status>)}</header>
            {!ro ? <div className="tp-body"><Skeleton h={60} /></div> : ro.conflicts.length === 0 ? <div className="tp-body tp-muted">No overlap, rest, availability, certification, site or max-hours conflicts in the {ro.view} roster. Break rules are nominal and unvalidated.</div> : (
              <ul className="tp-list" style={{ maxHeight: 260, overflow: 'auto' }}>{ro.conflicts.slice(0, 40).map((c, i) => (<li key={i} className="tp-item" style={{ gridTemplateColumns: 'auto 1fr', cursor: 'default' }}><Status tone="bad">{CONFLICT_LABEL[c.kind] ?? c.kind}</Status><span className="s">{c.detail}</span></li>))}</ul>
            )}
          </section>
          <section className="tp-card"><header><h2>Publication</h2></header>
            <div className="tp-body">
              {ro?.publication.latest_action_status ? <p style={{ marginTop: 0 }}>Last publish action: <Status tone={ro.publication.latest_action_status === 'confirmed' ? 'ok' : ro.publication.latest_action_status === 'unknown' ? 'risk' : 'neutral'}>{ro.publication.latest_action_status}</Status></p> : <p style={{ marginTop: 0 }} className="tp-muted">No publish action yet.</p>}
              <p className="tp-muted">A roster with unresolved hard conflicts cannot publish. Publishing runs validate → approve → execute → reconcile.</p>
              <Link className="tp-btn" style={{ textDecoration: 'none', display: 'inline-block' }} to={`/actions?site=${site.site_id}`}>Open Approvals</Link>
            </div>
          </section>
          <section className="tp-card"><header><h2>Basis</h2></header><div className="tp-body tp-muted" style={{ fontSize: 12.5 }}>{ro?.forecast.method}. {(ro?.notes ?? []).join(' ')}</div></section>
        </aside>
      </div>

      {picked && ro && (
        <Drawer title="Shift" onClose={() => setPicked(null)}>
          <dl className="tp-dl">
            <dt>Worker</dt><dd>{workers.find((w) => w.worker_id === picked.worker_id)?.label}</dd>
            <dt>Role / zone</dt><dd>{picked.role} · {picked.zone}</dd>
            <dt>Start</dt><dd>{fmtTime(picked.start_at, tz, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}</dd>
            <dt>End</dt><dd>{fmtTime(picked.end_at, tz, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}</dd>
            <dt>Break</dt><dd>{picked.break_minutes} min (nominal)</dd>
            <dt>Employment</dt><dd>{picked.employment_type}</dd>
            <dt>Status</dt><dd>{picked.status === 'committed' ? 'Published' : 'Draft (proposed)'}</dd>
            <dt>Conflicts</dt><dd>{ro.conflicts.filter((c) => c.shift_id === picked.shift_id).map((c) => c.detail).join('; ') || 'None'}</dd>
          </dl>
        </Drawer>
      )}
    </>
  )
}

function DayTimeline({ ro, day, tz, rows, flagged, onPick }: { ro: NonNullable<ReturnType<typeof useApi<import('../api/ops').Roster | null>>['data']>; day: string; tz: string; rows: { worker_id: string; label: string }[]; flagged: Set<string>; onPick: (s: RosterShift) => void }) {
  const dayStart = new Date(localMidnightUtc(day, tz)).getTime()
  const dayEnd = new Date(localMidnightUtc(addDays(day, 1), tz)).getTime()
  const pct = (t: number) => Math.max(0, Math.min(100, ((t - dayStart) / (dayEnd - dayStart)) * 100))
  return (
    <div className="tp-board" role="region" aria-label="Day timeline" tabIndex={0}>
      <table>
        <thead><tr><th className="tp-w" scope="col">Worker</th><th scope="col" style={{ minWidth: 720 }}><div style={{ display: 'flex', justifyContent: 'space-between' }}>{[0, 4, 8, 12, 16, 20, 24].map((h) => <span key={h}>{String(h % 24).padStart(2, '0')}:00</span>)}</div></th></tr></thead>
        <tbody>{rows.map((w) => {
          const sh = ro.shifts.filter((s) => s.worker_id === w.worker_id && new Date(s.end_at).getTime() > dayStart && new Date(s.start_at).getTime() < dayEnd)
          if (!sh.length) return null
          return (<tr key={w.worker_id}><th className="tp-w" scope="row">{w.label}</th><td><div className="tp-tl">{sh.map((s) => (
            <button key={s.shift_id} className={`bar tp-shift${flagged.has(s.shift_id) ? ' conflict' : ''}`} onClick={() => onPick(s)} style={{ position: 'absolute', top: 2, bottom: 2, margin: 0, left: `${pct(new Date(s.start_at).getTime())}%`, width: `${pct(new Date(s.end_at).getTime()) - pct(new Date(s.start_at).getTime())}%`, overflow: 'hidden', whiteSpace: 'nowrap' }} aria-label={`${w.label} ${fmtTime(s.start_at, tz)}–${fmtTime(s.end_at, tz)} ${s.role}`}>{s.role} {fmtTime(s.start_at, tz)}–{fmtTime(s.end_at, tz)}</button>))}</div></td></tr>)
        })}</tbody>
      </table>
    </div>
  )
}
