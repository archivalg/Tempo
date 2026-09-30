import { useCallback, useEffect, useState } from 'react'
import { approveSession, decideAdjustment, getTimesheets, requestAdjustment, type Timesheet, type TimesheetData } from '../api/ops'
import { ApiError } from '../api/client'
import { useSite } from '../components/AppShell'
import { Banner, Drawer, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { fmtTime, localDate } from '../lib/format'
import { utcToZonedInput, zonedToUtcIso } from '../lib/zoned'

const addDays = (date: string, n: number) => { const d = new Date(`${date}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const mondayOf = (date: string) => { const d = new Date(`${date}T00:00:00Z`); return addDays(date, -((d.getUTCDay() + 6) % 7)) }

export default function AttendancePage() {
  const { site } = useSite()
  const { can, access } = useTempoContext()
  const tz = site?.timezone ?? 'UTC'
  const [start, setStart] = useState(() => mondayOf(localDate(new Date(), tz)))
  const [data, setData] = useState<TimesheetData | null>(null)
  const [filter, setFilter] = useState<'all' | 'pending' | 'unrostered' | 'corrections'>('all')
  const [open, setOpen] = useState<Timesheet | null>(null)
  const [f, setF] = useState({ start: '', end: '', reason: '' })
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => { if (site) getTimesheets(site.site_id, start).then(setData).catch((e) => setErr(e.message)) }, [site, start])
  useEffect(() => { setData(null); load() }, [load])

  const rows = (data?.sessions ?? []).filter((r) => filter === 'all' || (filter === 'pending' && r.approval !== 'approved') || (filter === 'unrostered' && !r.matched) || (filter === 'corrections' && r.adjustment?.state === 'pending'))
  const openRow = (r: Timesheet) => { setOpen(r); setNote(''); setF({ start: utcToZonedInput(r.clock_in, tz), end: utcToZonedInput(r.clock_out ?? new Date().toISOString(), tz), reason: '' }) }
  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null)
    try { await fn(); setOpen(null); load() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Failed') } finally { setBusy(false) }
  }
  if (!site) return <Empty title="No site available" />
  const t = (iso: string | null) => (iso ? fmtTime(iso, tz, { weekday: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—')
  return (
    <>
      <PageHead title="Attendance & timesheets" sub={`${site.name} · week of ${start} · originals are never overwritten; corrections need a second approver`}>
        <div className="tp-row"><button className="tp-btn" onClick={() => setStart(addDays(start, -7))} aria-label="Previous week">←</button><button className="tp-btn" onClick={() => setStart(mondayOf(localDate(new Date(), tz)))}>This week</button><button className="tp-btn" onClick={() => setStart(addDays(start, 7))} aria-label="Next week">→</button></div>
      </PageHead>
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      <section className="tp-kpis">
        {[['Sessions', data?.summary.sessions], ['Open now', data?.summary.open], ['Approved (payable)', data?.summary.approved], ['Awaiting approval', data?.summary.pending], ['Unrostered', data?.summary.unrostered], ['Pending corrections', data?.summary.pending_adjustments]].map(([l, v]) => (
          <div key={l as string} className="tp-card tp-kpi"><div className="lbl">{l}</div>{data ? <div className="val">{v as number}</div> : <Skeleton h={26} w={50} />}</div>))}
      </section>
      <div className="tp-seg" role="group" aria-label="Filter" style={{ marginBottom: 12 }}>
        {(['all', 'pending', 'unrostered', 'corrections'] as const).map((k) => <button key={k} aria-pressed={filter === k} onClick={() => setFilter(k)}>{{ all: 'All', pending: 'Awaiting approval', unrostered: 'Unrostered', corrections: 'Corrections' }[k]}</button>)}
      </div>
      <section className="tp-card">
        {!data ? <div className="tp-body"><Skeleton h={200} /></div> : rows.length === 0 ? <Empty title="No sessions match">Nothing to show for this filter and week.</Empty> : (
          <div style={{ overflow: 'auto', maxHeight: 620 }}>
            <table className="tp-table tp-num">
              <thead><tr><th>Worker</th><th>Scheduled</th><th>Clock in</th><th>Clock out</th><th>Punched h</th><th>Status</th><th /></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.session_id}>
                  <td>{r.worker_label}<div className="tp-muted" style={{ fontSize: 12 }}>{r.role ?? 'no rostered shift'}</div></td>
                  <td>{r.scheduled_start ? `${t(r.scheduled_start)} → ${fmtTime(r.scheduled_end!, tz)}` : <Status tone="risk">Unrostered</Status>}</td>
                  <td>{t(r.clock_in)}</td><td>{r.open ? <Status tone="neutral">Open</Status> : t(r.clock_out)}</td>
                  <td>{r.punched_hours.toFixed(2)}</td>
                  <td>{r.approval === 'approved' ? <Status tone="ok">Approved · {r.payable_hours?.toFixed(2)} h</Status> : <Status tone="risk">Pending</Status>}{r.adjustment && <div><Status tone={r.adjustment.state === 'pending' ? 'risk' : r.adjustment.state === 'approved' ? 'ok' : 'bad'}>Correction {r.adjustment.state}</Status></div>}</td>
                  <td><button className="tp-btn" onClick={() => openRow(r)}>Open</button></td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </section>

      {open && (
        <Drawer title={`Timesheet — ${open.worker_label}`} onClose={() => setOpen(null)}>
          <div className="tp-stack">
            <dl className="tp-dl">
              <dt>Scheduled</dt><dd>{open.scheduled_start ? `${t(open.scheduled_start)} → ${fmtTime(open.scheduled_end!, tz)} (${open.scheduled_hours} h)` : 'Unrostered'}</dd>
              <dt>Original punches</dt><dd>{t(open.clock_in)} → {open.open ? 'still open' : t(open.clock_out)} ({open.punched_hours.toFixed(2)} h)</dd>
              <dt>Approval</dt><dd>{open.approval}</dd>
            </dl>
            {open.adjustment && (
              <Banner tone={open.adjustment.state === 'pending' ? 'warn' : 'info'} title={`Correction ${open.adjustment.state}`}>
                {t(open.adjustment.requested_start)} → {t(open.adjustment.requested_end)} — “{open.adjustment.reason}”{open.adjustment.decision_note ? ` (${open.adjustment.decision_note})` : ''}
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
            {can('labour.attendance.approve') && open.approval !== 'approved' && !open.open && (!open.adjustment || open.adjustment.state !== 'pending') && (
              <button className="tp-btn primary" disabled={busy} onClick={() => void act(() => approveSession(open.session_id))}>Approve timesheet as punched</button>
            )}
            {open.open && <p className="tp-muted">The worker is still clocked in; the timesheet can be approved after they clock out.</p>}
            {can('labour.attendance.approve') && open.approval !== 'approved' && !open.open && !open.adjustment?.state?.startsWith('pending') && (
              <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void act(() => requestAdjustment(open.session_id, zonedToUtcIso(f.start, tz), zonedToUtcIso(f.end, tz), f.reason)) }}>
                <h3 style={{ margin: '8px 0 0', fontSize: 14 }}>Request a correction</h3>
                <div className="tp-cols2"><label className="tp-field">In ({tz})<input type="datetime-local" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></label>
                  <label className="tp-field">Out ({tz})<input type="datetime-local" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></label></div>
                <label className="tp-field">Reason (required)<input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} /></label>
                <button className="tp-btn" disabled={busy || f.reason.trim().length < 5}>Submit correction for approval</button>
                <p className="tp-muted" style={{ fontSize: 12 }}>The original punch is kept. Payable time uses the correction only once another person approves it.</p>
              </form>
            )}
          </div>
        </Drawer>
      )}
    </>
  )
}
