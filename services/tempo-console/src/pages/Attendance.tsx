import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  approveMany, approveSession, decideAdjustment, exportCsv, exportPayroll, getSessionHistory, getTimesheets, reopenSession, requestAdjustment, requestMissingSession,
  type SessionHistory, type Timesheet, type TimesheetData,
} from '../api/ops'
import { ApiError } from '../api/client'
import { useSite } from '../components/AppShell'
import { AttendanceRules } from '../components/AttendanceRules'
import { AttendanceToday } from '../components/AttendanceToday'
import { ClockCredentials } from '../components/ClockCredentials'
import { Banner, ExportButton, Drawer, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { fmtTime, localDate } from '../lib/format'
import { utcToZonedInput, zonedToUtcIso } from '../lib/zoned'

const addDays = (date: string, n: number) => { const d = new Date(`${date}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const mondayOf = (date: string) => { const d = new Date(`${date}T00:00:00Z`); return addDays(date, -((d.getUTCDay() + 6) % 7)) }
type View = 'today' | 'timesheets' | 'rules' | 'badges'

export default function AttendancePage() {
  const { site } = useSite()
  const { can, access } = useTempoContext()
  const tz = site?.timezone ?? 'UTC'
  const [qs] = useSearchParams()
  const [view, setView] = useState<View>(() => (['today', 'timesheets', 'rules', 'badges'] as const).find((v) => v === qs.get('view')) ?? 'today')
  const [start, setStart] = useState(() => mondayOf(localDate(new Date(), tz)))
  const [data, setData] = useState<TimesheetData | null>(null)
  const [filter, setFilter] = useState<'all' | 'pending' | 'unrostered' | 'corrections'>('all')
  const [open, setOpen] = useState<Timesheet | null>(null)
  const [hist, setHist] = useState<SessionHistory | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [missing, setMissing] = useState(false)
  const [f, setF] = useState({ start: '', end: '', brk: '', reason: '' })
  const [m, setM] = useState({ worker: '', start: '', end: '', brk: '', reason: '' })
  const [note, setNote] = useState('')
  const [reopenReason, setReopenReason] = useState('')
  const [info, setInfo] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => { if (site) getTimesheets(site.site_id, start).then(setData).catch((e) => setErr(e.message)) }, [site, start])
  useEffect(() => { if (view === 'timesheets') { setData(null); load() } }, [load, view])
  useEffect(() => { if (open) { setHist(null); getSessionHistory(open.session_id).then(setHist).catch(() => setHist(null)) } }, [open])

  const rows = (data?.sessions ?? []).filter((r) => filter === 'all' || (filter === 'pending' && r.approval !== 'approved') || (filter === 'unrostered' && !r.matched) || (filter === 'corrections' && r.adjustment?.state === 'pending'))
  const approvable = rows.filter((r) => r.approval !== 'approved' && !r.open && r.adjustment?.state !== 'pending')
  const openRow = (r: Timesheet) => {
    setOpen(r); setNote(''); setReopenReason(''); setErr(null)
    setF({ start: utcToZonedInput(r.clock_in, tz), end: utcToZonedInput(r.clock_out ?? new Date().toISOString(), tz), brk: String(Math.round(r.break_hours * 60)), reason: '' })
  }
  async function act(fn: () => Promise<unknown>, after?: () => void) {
    setBusy(true); setErr(null); setInfo(null)
    try { await fn(); setOpen(null); setMissing(false); after?.(); load() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Failed') } finally { setBusy(false) }
  }
  if (!site) return <Empty title="No site available" />
  const t = (iso: string | null) => (iso ? fmtTime(iso, tz, { weekday: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—')
  const h2 = (n: number) => n.toFixed(2)
  const tabs: [View, string, boolean][] = [['today', 'Today', true], ['timesheets', 'Timesheets', true], ['rules', 'Rules', true], ['badges', 'Badges & PINs', can('labour.configure')]]
  return (
    <>
      <PageHead title="Attendance & timesheets" sub={`${site.name} · originals are never overwritten; corrections need a second approver`}>
        {view === 'timesheets' && can('labour.export') && <ExportButton run={() => exportCsv(site.site_id, 'timesheets', start)} label="Timesheet report" />}
        {view === 'timesheets' && can('labour.export') && can('labour.attendance.approve') && <ExportButton run={() => exportPayroll(site.site_id, start)} label="Payroll CSV (approved)" />}
        {view === 'timesheets' && <div className="tp-row"><button className="tp-btn" onClick={() => setStart(addDays(start, -7))} aria-label="Previous week">←</button><button className="tp-btn" onClick={() => setStart(mondayOf(localDate(new Date(), tz)))}>This week</button><button className="tp-btn" onClick={() => setStart(addDays(start, 7))} aria-label="Next week">→</button></div>}
      </PageHead>
      <div className="tp-seg" role="tablist" aria-label="Attendance views" style={{ marginBottom: 12 }}>
        {tabs.filter(([, , show]) => show).map(([k, label]) => <button key={k} role="tab" aria-selected={view === k} aria-pressed={view === k} onClick={() => { setView(k); setErr(null); setInfo(null) }}>{label}</button>)}
      </div>
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      {info && <Banner tone="info" title="Done">{info}</Banner>}

      {view === 'today' && <AttendanceToday siteId={site.site_id} tz={tz} initialDay={/^\d{4}-\d{2}-\d{2}$/.test(qs.get('date') ?? '') ? qs.get('date')! : undefined} onOpenTimesheets={() => setView('timesheets')} />}
      {view === 'rules' && <AttendanceRules siteId={site.site_id} canEdit={can('labour.configure')} />}
      {view === 'badges' && can('labour.configure') && <ClockCredentials siteId={site.site_id} />}

      {view === 'timesheets' && (<>
        <section className="tp-kpis">
          {[['Sessions', data?.summary.sessions], ['Open now', data?.summary.open], ['Approved (payable)', data?.summary.approved], ['Awaiting approval', data?.summary.pending], ['Unrostered', data?.summary.unrostered], ['Pending corrections', data?.summary.pending_adjustments]].map(([l, v]) => (
            <div key={l as string} className="tp-card tp-kpi"><div className="lbl">{l}</div>{data ? <div className="val">{v as number}</div> : <Skeleton h={26} w={50} />}</div>))}
        </section>
        <div className="tp-row" style={{ marginBottom: 12 }}>
          <div className="tp-seg" role="group" aria-label="Filter">
            {(['all', 'pending', 'unrostered', 'corrections'] as const).map((k) => <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{{ all: 'All', pending: 'Awaiting approval', unrostered: 'Unrostered', corrections: 'Corrections' }[k]}</button>)}
          </div>
          {can('labour.attendance.approve') && <>
            <button className="tp-btn primary" disabled={busy || picked.size === 0} onClick={() => void act(async () => { const r = await approveMany([...picked]); setInfo(`${r.approved.length} approved${r.skipped.length ? `; ${r.skipped.length} not approved — ${r.skipped.map((s) => s.reason).join('; ')}` : ''}`) }, () => setPicked(new Set()))}>Approve selected ({picked.size})</button>
            <button className="tp-btn" onClick={() => { setMissing(true); setErr(null); setM({ worker: '', start: '', end: '', brk: '', reason: '' }) }}>Add a missing timesheet</button></>}
        </div>
        <section className="tp-card">
          {!data ? <div className="tp-body"><Skeleton h={200} /></div> : rows.length === 0 ? <Empty title="No sessions match">Nothing to show for this filter and week.</Empty> : (
            <div style={{ overflow: 'auto', maxHeight: 620 }}>
              <table className="tp-table tp-num">
                <thead><tr><th>{approvable.length > 0 && can('labour.attendance.approve') && <input type="checkbox" aria-label="Select all approvable" checked={approvable.every((r) => picked.has(r.session_id))} onChange={(e) => setPicked(e.target.checked ? new Set(approvable.map((r) => r.session_id)) : new Set())} />}</th>
                  <th>Worker</th><th>Scheduled</th><th>Clock in</th><th>Clock out</th><th>Worked h</th><th>Break h</th><th>Payable h</th><th>Status</th><th /></tr></thead>
                <tbody>{rows.map((r) => (
                  <tr key={r.session_id}>
                    <td>{approvable.includes(r) && can('labour.attendance.approve') && <input type="checkbox" aria-label={`Select ${r.worker_label}`} checked={picked.has(r.session_id)} onChange={(e) => { const n = new Set(picked); if (e.target.checked) n.add(r.session_id); else n.delete(r.session_id); setPicked(n) }} />}</td>
                    <td>{r.worker_label}<div className="tp-muted" style={{ fontSize: 12 }}>{r.role ?? 'no rostered shift'}</div></td>
                    <td>{r.scheduled_start ? `${t(r.scheduled_start)} → ${fmtTime(r.scheduled_end!, tz)}` : <Status tone="risk">Unrostered</Status>}</td>
                    <td>{t(r.clock_in)}</td><td>{r.open ? <Status tone="neutral">{r.state === 'on_break' ? 'On break' : 'Open'}</Status> : r.clock_out ? t(r.clock_out) : <Status tone="risk">No clock-out</Status>}</td>
                    <td>{h2(r.worked_hours)}</td><td>{h2(r.break_hours)}{r.unpaid_break_hours === 0 && r.break_hours > 0 ? <div className="tp-muted" style={{ fontSize: 12 }}>paid</div> : null}</td>
                    <td>{r.approval === 'approved' ? <b>{r.payable_hours?.toFixed(2)}</b> : <span className="tp-muted" title="Payable hours are confirmed when the timesheet is approved">—</span>}</td>
                    <td>{r.approval === 'approved' ? <Status tone="ok">Approved{r.revision > 1 ? ` · rev ${r.revision}` : ''}</Status> : <Status tone="risk">Pending</Status>}{r.adjustment && <div><Status tone={r.adjustment.state === 'pending' ? 'risk' : r.adjustment.state === 'approved' ? 'ok' : 'bad'}>Correction {r.adjustment.state}</Status></div>}</td>
                    <td style={{ whiteSpace: 'nowrap' }}><button className="tp-btn" onClick={() => openRow(r)}>Open</button></td>
                  </tr>))}</tbody>
              </table>
            </div>
          )}
        </section>
        <p className="tp-muted" style={{ fontSize: 12 }}>Worked = first punch to last punch; break = recorded break time; payable = worked less unpaid breaks, rounded as the site’s Rules say, and only once approved. Tempo exports hours, not pay: awards and loadings are not interpreted.</p>
      </>)}

      {open && (
        <Drawer title={`Timesheet — ${open.worker_label}`} onClose={() => setOpen(null)}>
          <div className="tp-stack">
            <dl className="tp-dl">
              <dt>Scheduled</dt><dd>{open.scheduled_start ? `${t(open.scheduled_start)} → ${fmtTime(open.scheduled_end!, tz)} (${open.scheduled_hours} h)` : 'Unrostered'}</dd>
              <dt>Original punches</dt><dd>{t(open.clock_in)} → {open.open ? 'still open' : open.clock_out ? t(open.clock_out) : 'no clock-out recorded'} ({open.punched_hours.toFixed(2)} h)</dd>
              <dt>Worked / break / payable</dt><dd>{h2(open.worked_hours)} h / {h2(open.break_hours)} h{open.unpaid_break_hours === 0 && open.break_hours > 0 ? ' (paid)' : ''} / {open.approval === 'approved' ? `${open.payable_hours?.toFixed(2)} h` : 'when approved'}</dd>
              <dt>Approval</dt><dd>{open.approval === 'approved' ? `Approved by ${open.approved_by ?? 'unknown'}${open.revision > 1 ? ` (revision ${open.revision})` : ''}` : 'Pending'}</dd>
            </dl>
            {open.adjustment && (
              <Banner tone={open.adjustment.state === 'pending' ? 'warn' : 'info'} title={`Correction ${open.adjustment.state}`}>
                {t(open.adjustment.requested_start)} → {t(open.adjustment.requested_end)}{open.adjustment.requested_break_minutes != null ? `, break ${open.adjustment.requested_break_minutes} min` : ''} — “{open.adjustment.reason}”{open.adjustment.decision_note ? ` (${open.adjustment.decision_note})` : ''}
              </Banner>
            )}
            {open.adjustment?.state === 'pending' && can('labour.approve') && open.adjustment.requested_by !== access?.user_id && (
              <div className="tp-stack">
                <label className="tp-field">Decision note (required to reject)<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
                <div className="tp-row"><button className="tp-btn primary" disabled={busy} onClick={() => void act(() => decideAdjustment(open.adjustment!.id, true, note))}>Approve correction</button>
                  <button className="tp-btn danger" disabled={busy || note.trim().length < 3} onClick={() => void act(() => decideAdjustment(open.adjustment!.id, false, note.trim()))}>Reject</button></div>
              </div>
            )}
            {open.adjustment?.state === 'pending' && open.adjustment.requested_by === access?.user_id && <p className="tp-muted">You requested this correction; someone else must decide it.</p>}
            {can('labour.attendance.approve') && open.approval !== 'approved' && !open.open && (!open.adjustment || open.adjustment.state !== 'pending') && open.clock_out && (
              <button className="tp-btn primary" disabled={busy} onClick={() => void act(() => approveSession(open.session_id))}>Approve timesheet as punched</button>
            )}
            {open.open && <p className="tp-muted">The worker is still clocked in. If they have left, request a correction with the real finish time; once approved it closes this session.</p>}
            {open.approval === 'approved' && can('labour.attendance.approve') && (
              <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void act(() => reopenSession(open.session_id, reopenReason.trim())) }}>
                <h3 style={{ margin: '8px 0 0', fontSize: 14 }}>Reopen this approved timesheet</h3>
                <label className="tp-field">Reason (at least 10 characters)<input value={reopenReason} onChange={(e) => setReopenReason(e.target.value)} /></label>
                <button className="tp-btn" disabled={busy || reopenReason.trim().length < 10}>Reopen — records revision {open.revision + 1}</button>
                <p className="tp-muted" style={{ fontSize: 12 }}>Reopening removes it from payroll exports until it is approved again. The figures that were approved are kept in its history.</p>
              </form>
            )}
            {can('labour.attendance.approve') && open.approval !== 'approved' && !open.adjustment?.state?.startsWith('pending') && (
              <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void act(() => requestAdjustment(open.session_id, zonedToUtcIso(f.start, tz), zonedToUtcIso(f.end, tz), f.reason, f.brk === '' ? null : Number(f.brk))) }}>
                <h3 style={{ margin: '8px 0 0', fontSize: 14 }}>Request a correction</h3>
                <div className="tp-cols2"><label className="tp-field">In ({tz})<input type="datetime-local" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></label>
                  <label className="tp-field">Out ({tz})<input type="datetime-local" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></label></div>
                <label className="tp-field">Break (minutes)<input type="number" min={0} max={600} value={f.brk} onChange={(e) => setF({ ...f, brk: e.target.value })} /></label>
                <label className="tp-field">Reason (required)<input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></label>
                <button className="tp-btn" disabled={busy || f.reason.trim().length < 5}>Submit correction for approval</button>
                <p className="tp-muted" style={{ fontSize: 12 }}>The original punches are kept. Payable time uses the correction only once another person approves it.</p>
              </form>
            )}
            <details><summary>History: punches, corrections and revisions</summary>
              {!hist ? <Skeleton h={60} /> : (
                <ul style={{ paddingLeft: 18, fontSize: 13 }}>
                  {hist.punches.map((p, i) => <li key={`p${i}`}>{t(p.at)} — {p.kind.replace('_', ' ')} <span className="tp-muted">({p.source}{p.note ? `: ${p.note}` : ''})</span></li>)}
                  {hist.corrections.map((c) => <li key={c.id}>Correction {c.state} — “{c.reason}” <span className="tp-muted">requested by {c.requested_by}{c.decided_by ? `, decided by ${c.decided_by}` : ''}</span></li>)}
                  {hist.revisions.map((r, i) => <li key={`r${i}`}>{t(r.at)} — {r.action} (revision {r.revision}) by {r.actor}{r.reason ? ` — “${r.reason}”` : ''}</li>)}
                </ul>)}
            </details>
          </div>
        </Drawer>
      )}

      {missing && (
        <Drawer title="Add a missing timesheet" onClose={() => setMissing(false)}>
          <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void act(() => requestMissingSession(site.site_id, { worker_id: m.worker.trim(), start_at: zonedToUtcIso(m.start, tz), end_at: zonedToUtcIso(m.end, tz), break_minutes: m.brk === '' ? null : Number(m.brk), reason: m.reason.trim() }), () => setInfo('Submitted. It becomes a timesheet once another person approves it.')) }}>
            <p className="tp-muted">For someone who worked but never punched (for example the kiosk was down). Nothing is recorded until a second person approves; the approved entry is marked as a correction, not a punch.</p>
            <label className="tp-field">Worker ID<input value={m.worker} onChange={(e) => setM({ ...m, worker: e.target.value })} required /></label>
            <div className="tp-cols2"><label className="tp-field">Start ({tz})<input type="datetime-local" value={m.start} onChange={(e) => setM({ ...m, start: e.target.value })} required /></label>
              <label className="tp-field">End ({tz})<input type="datetime-local" value={m.end} onChange={(e) => setM({ ...m, end: e.target.value })} required /></label></div>
            <label className="tp-field">Break (minutes)<input type="number" min={0} max={600} value={m.brk} onChange={(e) => setM({ ...m, brk: e.target.value })} /></label>
            <label className="tp-field">Reason (at least 10 characters)<input value={m.reason} onChange={(e) => setM({ ...m, reason: e.target.value })} required /></label>
            <button className="tp-btn primary" disabled={busy || !m.worker || !m.start || !m.end || m.reason.trim().length < 10}>Submit for approval</button>
          </form>
        </Drawer>
      )}
    </>
  )
}
