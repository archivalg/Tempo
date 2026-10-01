import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import {
  addShift, approveRoster, copyPublished, deleteShift, editShift, generateRoster, getVersionBoard, getVersionEvents, listRosterVersions, publishRoster, rejectRoster, submitRoster,
  type RosterEventItem, type RosterShift, type RosterVersion, type VersionBoard,
} from '../api/ops'
import { ApiError } from '../api/client'
import { useSite } from '../components/AppShell'
import { Banner, Drawer, Empty, PageHead, RosterSteps, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { fmtMoney, fmtNum, fmtTime, localDate } from '../lib/format'
import { localMidnightUtc, utcToZonedInput, zonedToUtcIso } from '../lib/zoned'

const EMP: Record<string, string> = { permanent: 'PT', casual: 'CA', labour_hire: 'LH' }
const CONFLICT_LABEL: Record<string, string> = { overlap: 'Overlap', rest: 'Rest', availability: 'Availability', certification: 'Certification', site_eligibility: 'Site eligibility', max_hours: 'Max hours' }
const addDays = (date: string, n: number) => { const d = new Date(`${date}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const mondayOf = (date: string) => { const d = new Date(`${date}T00:00:00Z`); return addDays(date, -((d.getUTCDay() + 6) % 7)) }
const errText = (e: unknown) => (e instanceof ApiError ? e.message : e instanceof Error ? e.message : 'Something went wrong')

type Draft = { shift_id?: string; worker_id: string; role: string; zone: string; start: string; end: string }
type Confirm = null | { kind: 'publish' | 'reject' | 'approve' | 'reoptimise' | 'copy'; note: string }

export default function RosterPlannerPage() {
  const { site } = useSite()
  const { can, access } = useTempoContext()
  const [params, setParams] = useSearchParams()
  const tz = site?.timezone ?? 'UTC'
  const start = params.get('start') ?? mondayOf(localDate(new Date(), tz))
  const [versions, setVersions] = useState<RosterVersion[] | null>(null)
  const [board, setBoard] = useState<VersionBoard | null>(null)
  const [events, setEvents] = useState<RosterEventItem[] | null>(null)
  const [mode, setMode] = useState<'week' | 'day'>('week')
  const [dayIdx, setDayIdx] = useState(0)
  const [filter, setFilter] = useState('')
  const [zone, setZone] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [edit, setEdit] = useState<Draft | null>(null)
  const [confirm, setConfirm] = useState<Confirm>(null)
  const [showEvents, setShowEvents] = useState(false)
  const [loading, setLoading] = useState(true)
  const [dragId, setDragId] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const [moved, setMoved] = useState<{ label: string; undo: () => void } | null>(null)
  useEffect(() => setMoved(null), [board?.version.id])
  const set = (k: string, v: string | null) => { const p = new URLSearchParams(params); if (v == null) p.delete(k); else p.set(k, v); setParams(p, { replace: true }) }
  const wantV = params.get('v')

  const load = useCallback(async () => {
    if (!site) return
    setLoading(true); setErr(null)
    try {
      const vs = await listRosterVersions(site.site_id, start)
      setVersions(vs)
      const pick = vs.find((v) => v.id === wantV) ?? vs.find((v) => !['superseded', 'cancelled'].includes(v.state)) ?? null
      setBoard(pick ? await getVersionBoard(pick.id) : null)
    } catch (e) { setErr(errText(e)) } finally { setLoading(false) }
  }, [site, start, wantV])
  useEffect(() => { void load() }, [load])
  useEffect(() => { setEvents(null); if (showEvents && board) getVersionEvents(board.version.id).then(setEvents).catch(() => setEvents([])) }, [showEvents, board?.version.id, board?.version.state]) // eslint-disable-line react-hooks/exhaustive-deps

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(start, i)), [start])
  const v = board?.version
  const workers = board?.workers ?? []
  const byWorkerDay = useMemo(() => {
    const m = new Map<string, RosterShift[]>()
    for (const s of board?.shifts ?? []) { const k = `${s.worker_id}|${localDate(new Date(s.start_at), tz)}`; m.set(k, [...(m.get(k) ?? []), s]) }
    return m
  }, [board, tz])
  const shown = workers.filter((w) => (!filter || w.label.toLowerCase().includes(filter.toLowerCase()) || w.skills.some((s) => s.includes(filter.toLowerCase()))) && (!zone || (board?.shifts ?? []).some((s) => s.worker_id === w.worker_id && s.zone === zone)))
  const zones = useMemo(() => [...new Set((board?.shifts ?? []).map((s) => s.zone))].sort(), [board])
  const flagged = new Set((board?.conflicts ?? []).map((c) => c.shift_id))
  const editable = !!v && !['published', 'reconciled', 'superseded', 'cancelled', 'publishing'].includes(v.state) && can('labour.plan')

  async function run<T>(label: string, fn: () => Promise<T>, after?: (r: T) => void) {
    setBusy(label); setErr(null)
    try { const r = await fn(); after?.(r) } catch (e) { setErr(errText(e)) } finally { setBusy(null) }
  }
  const adopt = (b: VersionBoard) => { setBoard(b); setVersions(b.versions); set('v', b.version.id) }
  const openNew = (worker: string, day: string) => setEdit({ worker_id: worker, role: workers.find((w) => w.worker_id === worker)?.skills[0] ?? 'picker', zone: zones[0] ?? 'pick_a', start: `${day}T06:00`, end: `${day}T14:00` })
  const openEdit = (s: RosterShift) => setEdit({ shift_id: s.shift_id, worker_id: s.worker_id, role: s.role, zone: s.zone, start: utcToZonedInput(s.start_at, tz), end: utcToZonedInput(s.end_at, tz) })

  /** Drag a shift to another worker and/or day. Same local start time and length; the server re-validates (overlap, rest, availability, certification…) and any conflict is flagged on the board. */
  async function moveShift(shiftId: string, workerId: string, day: string) {
    const s = board?.shifts.find((x) => x.shift_id === shiftId)
    if (!s || !v) return
    const from = { worker_id: s.worker_id, start_at: s.start_at, end_at: s.end_at }
    const dur = new Date(s.end_at).getTime() - new Date(s.start_at).getTime()
    const startUtc = zonedToUtcIso(`${day}T${utcToZonedInput(s.start_at, tz).slice(11)}`, tz)
    const to = { worker_id: workerId, start_at: startUtc, end_at: new Date(new Date(startUtc).getTime() + dur).toISOString() }
    if (to.worker_id === from.worker_id && to.start_at === from.start_at) return
    const body = (t: typeof from) => ({ worker_id: t.worker_id, role: s.role, zone: s.zone, start_at: t.start_at, end_at: t.end_at })
    const who = workers.find((w) => w.worker_id === workerId)?.label ?? workerId
    await run('move', () => editShift(v.id, shiftId, body(to)), (b) => {
      adopt(b)
      setMoved({ label: `Moved ${s.role} shift to ${who}, ${fmtTime(to.start_at, tz, { weekday: 'short', day: '2-digit' })}. The server re-checked the rules.`, undo: () => { setMoved(null); void run('move', () => editShift(v.id, shiftId, body(from)), adopt) } })
    })
  }

  async function saveShift() {
    if (!edit || !v) return
    const body = { worker_id: edit.worker_id, role: edit.role.trim(), zone: edit.zone.trim(), start_at: zonedToUtcIso(edit.start, tz), end_at: zonedToUtcIso(edit.end, tz) }
    await run('save', () => (edit.shift_id ? editShift(v.id, edit.shift_id, body) : addShift(v.id, body)), (b) => { adopt(b); setEdit(null) })
  }

  if (!site) return <Empty title="No site available" />
  const cur = board?.totals[v && ['published', 'reconciled'].includes(v.state) ? 'published' : 'draft']
  const live = board?.totals.published
  return (
    <>
      <PageHead title="Roster Planner" sub={<>{site.name} · week of {days[0]} · times in {tz}</>}>
        <div className="tp-seg" role="group" aria-label="Range"><button aria-pressed={mode === 'week'} onClick={() => setMode('week')}>Week</button><button aria-pressed={mode === 'day'} onClick={() => setMode('day')}>Day</button></div>
        <div className="tp-row" role="group" aria-label="Date navigator">
          <button className="tp-btn" onClick={() => { set('start', addDays(start, -7)); set('v', null) }} aria-label="Previous week">←</button>
          <button className="tp-btn" onClick={() => { set('start', null); set('v', null) }}>This week</button>
          <button className="tp-btn" onClick={() => { set('start', addDays(start, 7)); set('v', null) }} aria-label="Next week">→</button>
        </div>
      </PageHead>

      {err && <Banner tone="bad" title="That didn’t work">{err}</Banner>}
      {board && site.operating_mode === 'overlay' && <Banner tone="info" title="Overlay site">The roster of record is in the external system. Publication back needs a vendor-specific approval gate that is not enabled.</Banner>}

      <section className="tp-card" style={{ marginBottom: 12 }} aria-label="Roster version and workflow">
        <div className="tp-body tp-row" style={{ justifyContent: 'space-between' }}>
          <div className="tp-stack" style={{ gap: 6 }}>
            {v ? (<>
              <div className="tp-row">
                <label className="tp-field" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>Version
                  <select value={v.id} onChange={(e) => set('v', e.target.value)}>{(versions ?? []).map((x) => <option key={x.id} value={x.id}>v{x.version_no} · {x.state.replace('_', ' ')} · {x.source === 'solver' ? 'optimiser' : x.source.replace(/_/g, ' ')}</option>)}</select></label>
                <button className="tp-btn" onClick={() => setShowEvents(true)}>History</button>
              </div>
              <RosterSteps state={v.state} />
            </>) : <span className="tp-muted">{loading ? 'Loading…' : 'No roster exists for this week yet.'}</span>}
          </div>
          <div className="tp-row">
            {!v && can('labour.plan') && <button className="tp-btn primary" disabled={!!busy} onClick={() => void run('gen', () => generateRoster(site.site_id, start), adopt)}>{busy === 'gen' ? 'Generating… (running solver)' : 'Generate draft from forecast'}</button>}
            {v && v.state === 'draft' && can('labour.plan') && (<>
              <button className="tp-btn" disabled={!!busy} onClick={() => setConfirm({ kind: 'reoptimise', note: '' })}>Re-optimise</button>
              <button className="tp-btn primary" disabled={!!busy || board!.hard_conflicts > 0 || board!.shifts.length === 0} title={board!.hard_conflicts ? 'Resolve hard conflicts first' : ''}
                onClick={() => void run('submit', () => submitRoster(v.id), () => void load())}>{busy === 'submit' ? 'Submitting…' : 'Submit for approval'}</button>
            </>)}
            {v && v.state === 'pending_approval' && can('labour.approve') && v.submitted_by !== access?.user_id && (<>
              <button className="tp-btn danger" disabled={!!busy} onClick={() => setConfirm({ kind: 'reject', note: '' })}>Reject</button>
              <button className="tp-btn primary" disabled={!!busy} onClick={() => setConfirm({ kind: 'approve', note: '' })}>Approve</button>
            </>)}
            {v && v.state === 'pending_approval' && v.submitted_by === access?.user_id && <Status tone="risk">Awaiting a different approver</Status>}
            {v && v.state === 'approved' && can('labour.approve') && <button className="tp-btn primary" disabled={!!busy || board!.hard_conflicts > 0} onClick={() => setConfirm({ kind: 'publish', note: '' })}>Publish roster</button>}
            {v && ['published', 'reconciled'].includes(v.state) && can('labour.plan') && <button className="tp-btn" disabled={!!busy} onClick={() => setConfirm({ kind: 'copy', note: '' })}>Adjust (copy to new draft)</button>}
            {v && v.state === 'rejected' && <Status tone="bad">Rejected{v.decision_note ? `: ${v.decision_note}` : ''}</Status>}
          </div>
        </div>
      </section>

      {board && (
        <div className="tp-band" aria-label="Demand coverage by day">
          <div className="tp-muted" style={{ alignSelf: 'center', fontSize: 12 }}>Required vs rostered hours (this version)</div>
          {board.coverage_band.map((b) => (
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
            {editable && <button className="tp-btn" onClick={() => openNew(workers[0]?.worker_id ?? '', days[mode === 'day' ? dayIdx : 0])}>Add shift</button>}
            <span className="tp-muted">{shown.length} of {workers.length} workers</span>
          </div>
          {loading && !board ? <Skeleton h={360} /> : !board || board.shifts.length === 0 ? <Empty title="No shifts in this version">{can('labour.plan') ? 'Generate a draft from the forecast, or add shifts by hand.' : 'Nothing has been rostered.'}</Empty> : mode === 'week' ? (
            <div className="tp-board" role="region" aria-label="Roster board, scrollable" tabIndex={0}>
              <table>
                <caption className="tp-sr-only">Roster: workers by day. Each cell lists that worker’s shifts. {editable ? 'Use the add and shift buttons to edit.' : ''}</caption>
                <thead><tr><th className="tp-w" scope="col">Worker</th>{days.map((d) => <th key={d} scope="col">{fmtTime(`${d}T12:00:00Z`, 'UTC', { weekday: 'short', day: '2-digit', month: 'short' })}</th>)}</tr></thead>
                <tbody>
                  {shown.map((w) => (
                    <tr key={w.worker_id}>
                      <th className="tp-w" scope="row"><div style={{ fontWeight: 600 }}>{w.label}<span className="tp-emp" title={w.employment_type}>{EMP[w.employment_type] ?? w.employment_type}</span></div><div className="tp-muted" style={{ fontSize: 11 }}>{w.skills.join(' · ')}</div></th>
                      {days.map((d) => (
                        <td key={d} className={over === `${w.worker_id}|${d}` ? 'tp-drop' : undefined}
                          onDragOver={editable && dragId ? (e) => { e.preventDefault(); setOver(`${w.worker_id}|${d}`) } : undefined}
                          onDragLeave={() => setOver((o) => (o === `${w.worker_id}|${d}` ? null : o))}
                          onDrop={editable ? (e) => { e.preventDefault(); const id = e.dataTransfer.getData('text/plain') || dragId; setOver(null); setDragId(null); if (id) void moveShift(id, w.worker_id, d) } : undefined}>{(byWorkerDay.get(`${w.worker_id}|${d}`) ?? []).map((s) => (
                          <button key={s.shift_id} draggable={editable} onDragStart={(e) => { e.dataTransfer.setData('text/plain', s.shift_id); e.dataTransfer.effectAllowed = 'move'; setDragId(s.shift_id) }} onDragEnd={() => { setDragId(null); setOver(null) }} className={`tp-shift${dragId === s.shift_id ? ' dragging' : ''}${v && v.state !== 'published' && v.state !== 'reconciled' ? ' draft' : ''}${flagged.has(s.shift_id) ? ' conflict' : ''}`} onClick={() => openEdit(s)}
                            aria-label={`${w.label}, ${s.role} in ${s.zone}, ${fmtTime(s.start_at, tz)} to ${fmtTime(s.end_at, tz)}${flagged.has(s.shift_id) ? ', has a hard conflict' : ''}. ${editable ? 'Open to edit.' : 'Open details.'}`}>
                            <b>{fmtTime(s.start_at, tz)}–{fmtTime(s.end_at, tz)}</b> {flagged.has(s.shift_id) && <span aria-hidden="true">✕</span>}<br />{s.role} · {s.zone}
                          </button>))}
                          {editable && <button className="tp-add" onClick={() => openNew(w.worker_id, d)} aria-label={`Add shift for ${w.label} on ${d}`}>+ shift</button>}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <DayTimeline board={board} day={days[dayIdx]} tz={tz} rows={shown} flagged={flagged} onPick={openEdit} />
          )}
          <div role="status" aria-live="polite">{moved && <span className="tp-badge ok"><span aria-hidden="true">✓</span>{moved.label} <button className="tp-btn" onClick={moved.undo}>Undo</button></span>}</div>
          <div className="tp-muted" style={{ fontSize: 12 }}>PT permanent · CA casual · LH labour hire. Drag a shift to another worker or day, or open it to edit by form (the keyboard and screen-reader route). Every change is re-validated by the server.</div>
        </div>

        <aside className="tp-stack" aria-label="Insights">
          <section className="tp-card"><header><h2>{v && ['published', 'reconciled'].includes(v.state) ? 'Published roster' : 'This version vs published'}</h2></header>
            <div className="tp-body">
              {!board || !cur ? <Skeleton h={120} /> : (
                <table className="tp-table tp-num"><thead><tr><th></th><th>This version</th>{!['published', 'reconciled'].includes(v!.state) && <th>Published</th>}</tr></thead>
                  <tbody>
                    {([['Shifts', 'shifts'], ['Workers', 'workers'], ['Hours', 'hours']] as const).map(([lbl, k]) => (<tr key={k}><td>{lbl}</td><td>{fmtNum(cur[k])}</td>{!['published', 'reconciled'].includes(v!.state) && <td>{fmtNum(live![k])}</td>}</tr>))}
                    <tr><td>Agency share</td><td>{cur.agency_share_pct != null ? `${cur.agency_share_pct}%` : '—'}</td>{!['published', 'reconciled'].includes(v!.state) && <td>{live!.agency_share_pct != null ? `${live!.agency_share_pct}%` : '—'}</td>}</tr>
                    {'cost' in cur && <tr><td>Cost</td><td>{cur.cost != null ? fmtMoney(cur.cost) : 'withheld'}</td>{!['published', 'reconciled'].includes(v!.state) && <td>{live!.cost != null ? fmtMoney(live!.cost) : '—'}</td>}</tr>}
                  </tbody></table>
              )}
              {cur?.cost_note && <p className="tp-muted">{cur.cost_note}</p>}
            </div>
          </section>
          <section className="tp-card"><header><h2>Hard conflicts</h2>{board && (board.hard_conflicts === 0 ? <Status tone="ok">None</Status> : <Status tone="bad">{board.hard_conflicts}</Status>)}</header>
            {!board ? <div className="tp-body tp-muted">Nothing to validate.</div> : board.conflicts.length === 0 ? <div className="tp-body tp-muted">No overlap, rest (10h), availability, certification, site or max-hours conflicts. Break rules are nominal and unvalidated.</div> : (
              <ul className="tp-list" style={{ maxHeight: 260, overflow: 'auto' }}>{board.conflicts.slice(0, 40).map((c, i) => (<li key={i} className="tp-item" style={{ gridTemplateColumns: 'auto 1fr', cursor: 'default' }}><Status tone="bad">{CONFLICT_LABEL[c.kind] ?? c.kind}</Status><span className="s">{c.detail}</span></li>))}</ul>
            )}
          </section>
          <section className="tp-card"><header><h2>Approval &amp; publication</h2></header>
            <div className="tp-body">
              {!v ? <span className="tp-muted">No version yet.</span> : (
                <dl className="tp-dl" style={{ gridTemplateColumns: '110px 1fr' }}>
                  <dt>State</dt><dd>{v.state.replace('_', ' ')}</dd>
                  <dt>Submitted</dt><dd>{v.submitted_at ? fmtTime(v.submitted_at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}</dd>
                  <dt>Approved</dt><dd>{v.approved_at ? `${fmtTime(v.approved_at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}${v.decision_note ? ` — “${v.decision_note}”` : ''}` : '—'}</dd>
                  <dt>Published</dt><dd>{v.published_at ? fmtTime(v.published_at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}</dd>
                  <dt>Reconciled</dt><dd>{v.reconciliation?.checks ? (Object.values(v.reconciliation.checks).every(Boolean) ? <Status tone="ok">All checks passed</Status> : <Status tone="risk">Unknown — check failed</Status>) : '—'}</dd>
                </dl>
              )}
              <p className="tp-muted" style={{ fontSize: 12.5 }}>Editing after submission returns the roster to draft and invalidates the approval. The submitter can’t approve their own roster.</p>
              <Link to="/approvals" className="tp-btn" style={{ textDecoration: 'none', display: 'inline-block' }}>Open Approvals</Link>
            </div>
          </section>
          <section className="tp-card"><header><h2>Basis</h2></header><div className="tp-body tp-muted" style={{ fontSize: 12.5 }}>{board?.forecast.method}. {(board?.notes ?? []).join(' ')}</div></section>
        </aside>
      </div>

      {edit && v && (
        <Drawer title={edit.shift_id ? (editable ? 'Edit shift' : 'Shift') : 'Add shift'} onClose={() => setEdit(null)}>
          <form onSubmit={(e) => { e.preventDefault(); void saveShift() }} className="tp-stack">
            {v.state === 'pending_approval' || v.state === 'approved' ? <Banner tone="warn" title="Editing will invalidate the approval">The roster returns to draft and must be re-submitted.</Banner> : null}
            <label className="tp-field">Worker<select value={edit.worker_id} disabled={!editable} onChange={(e) => setEdit({ ...edit, worker_id: e.target.value })}>{workers.map((w) => <option key={w.worker_id} value={w.worker_id}>{w.label} ({EMP[w.employment_type]}) — {w.skills.join(', ')}</option>)}</select></label>
            <div className="tp-cols2">
              <label className="tp-field">Role<input value={edit.role} disabled={!editable} onChange={(e) => setEdit({ ...edit, role: e.target.value })} /></label>
              <label className="tp-field">Zone<input value={edit.zone} disabled={!editable} onChange={(e) => setEdit({ ...edit, zone: e.target.value })} list="zones" /></label>
            </div>
            <datalist id="zones">{zones.map((z) => <option key={z} value={z} />)}</datalist>
            <div className="tp-cols2">
              <label className="tp-field">Starts ({tz})<input type="datetime-local" value={edit.start} disabled={!editable} onChange={(e) => setEdit({ ...edit, start: e.target.value })} /></label>
              <label className="tp-field">Ends ({tz})<input type="datetime-local" value={edit.end} disabled={!editable} onChange={(e) => setEdit({ ...edit, end: e.target.value })} /></label>
            </div>
            {edit.shift_id && board!.conflicts.filter((c) => c.shift_id === edit.shift_id).map((c, i) => <Banner key={i} tone="bad" title={CONFLICT_LABEL[c.kind] ?? c.kind}>{c.detail}</Banner>)}
            {editable ? (
              <div className="tp-row">
                <button className="tp-btn primary" type="submit" disabled={!!busy}>{busy === 'save' ? 'Saving…' : 'Save & re-validate'}</button>
                {edit.shift_id && <button className="tp-btn danger" type="button" disabled={!!busy} onClick={() => void run('del', () => deleteShift(v.id, edit.shift_id!), (b) => { adopt(b); setEdit(null) })}>Remove shift</button>}
              </div>
            ) : <p className="tp-muted">This version is {v.state.replace('_', ' ')} — use “Adjust (copy to new draft)” to change it.</p>}
          </form>
        </Drawer>
      )}

      {confirm && v && (
        <Drawer title={{ publish: 'Publish this roster?', reject: 'Reject roster', approve: 'Approve roster', reoptimise: 'Re-optimise?', copy: 'Copy to a new draft?' }[confirm.kind]} onClose={() => setConfirm(null)}>
          <div className="tp-stack">
            {confirm.kind === 'publish' && <Banner tone="warn" title="This replaces the roster currently live for this week">Workers will see these shifts; the previous published rows are marked superseded (kept for audit). {board!.hard_conflicts} hard conflicts.</Banner>}
            {confirm.kind === 'reoptimise' && <Banner tone="warn" title="Your manual edits in this draft will be superseded">A new draft is produced from the current forecast and rules.</Banner>}
            {confirm.kind === 'copy' && <p>Creates an editable draft of the published shifts. The live roster is unchanged until the draft is approved and published.</p>}
            {(confirm.kind === 'approve' || confirm.kind === 'reject') && (
              <label className="tp-field">{confirm.kind === 'reject' ? 'Reason (required)' : 'Note (optional)'}<textarea rows={3} value={confirm.note} onChange={(e) => setConfirm({ ...confirm, note: e.target.value })} /></label>
            )}
            <div className="tp-row">
              <button className="tp-btn primary" disabled={!!busy || (confirm.kind === 'reject' && confirm.note.trim().length < 3)} onClick={() => {
                const k = confirm.kind, n = confirm.note.trim()
                void run(k, async () => {
                  if (k === 'approve') return approveRoster(v.id, n)
                  if (k === 'reject') return rejectRoster(v.id, n)
                  if (k === 'publish') return publishRoster(v.id)
                  if (k === 'reoptimise') return generateRoster(site.site_id, start)
                  return copyPublished(site.site_id, start)
                }, (r) => { setConfirm(null); if ('versions' in (r as object)) adopt(r as VersionBoard); else void load() })
              }}>{busy ? 'Working…' : { publish: 'Publish now', reject: 'Reject', approve: 'Approve', reoptimise: 'Re-optimise', copy: 'Create draft' }[confirm.kind]}</button>
              <button className="tp-btn" onClick={() => setConfirm(null)}>Cancel</button>
            </div>
          </div>
        </Drawer>
      )}

      {showEvents && v && (
        <Drawer title={`History — v${v.version_no}`} onClose={() => setShowEvents(false)}>
          {!events ? <Skeleton h={120} /> : (
            <ol className="tp-list" style={{ paddingLeft: 0 }}>{events.map((e, i) => (
              <li key={i} className="tp-item" style={{ gridTemplateColumns: '1fr', cursor: 'default' }}>
                <span className="t">{e.action.replace(/_/g, ' ')}</span>
                <span className="s">{fmtTime(e.at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })} · user …{e.actor.slice(-6)}</span>
                {Object.keys(e.detail).length > 0 && <span className="s" style={{ fontFamily: 'var(--tp-font-mono)' }}>{JSON.stringify(e.detail).slice(0, 220)}</span>}
              </li>))}</ol>
          )}
        </Drawer>
      )}
    </>
  )
}

function DayTimeline({ board, day, tz, rows, flagged, onPick }: { board: VersionBoard; day: string; tz: string; rows: { worker_id: string; label: string }[]; flagged: Set<string>; onPick: (s: RosterShift) => void }) {
  const dayStart = new Date(localMidnightUtc(day, tz)).getTime()
  const dayEnd = new Date(localMidnightUtc(addDays(day, 1), tz)).getTime()
  const pct = (t: number) => Math.max(0, Math.min(100, ((t - dayStart) / (dayEnd - dayStart)) * 100))
  return (
    <div className="tp-board" role="region" aria-label="Day timeline" tabIndex={0}>
      <table>
        <thead><tr><th className="tp-w" scope="col">Worker</th><th scope="col" style={{ minWidth: 720 }}><div style={{ display: 'flex', justifyContent: 'space-between' }}>{[0, 4, 8, 12, 16, 20, 24].map((h) => <span key={h}>{String(h % 24).padStart(2, '0')}:00</span>)}</div></th></tr></thead>
        <tbody>{rows.map((w) => {
          const sh = board.shifts.filter((s) => s.worker_id === w.worker_id && new Date(s.end_at).getTime() > dayStart && new Date(s.start_at).getTime() < dayEnd)
          if (!sh.length) return null
          return (<tr key={w.worker_id}><th className="tp-w" scope="row">{w.label}</th><td><div className="tp-tl">{sh.map((s) => (
            <button key={s.shift_id} className={`bar tp-shift${flagged.has(s.shift_id) ? ' conflict' : ''}`} onClick={() => onPick(s)} style={{ position: 'absolute', top: 2, bottom: 2, margin: 0, left: `${pct(new Date(s.start_at).getTime())}%`, width: `${pct(new Date(s.end_at).getTime()) - pct(new Date(s.start_at).getTime())}%`, overflow: 'hidden', whiteSpace: 'nowrap' }} aria-label={`${w.label} ${fmtTime(s.start_at, tz)}–${fmtTime(s.end_at, tz)} ${s.role}`}>{s.role} {fmtTime(s.start_at, tz)}–{fmtTime(s.end_at, tz)}</button>))}</div></td></tr>)
        })}</tbody>
      </table>
    </div>
  )
}
