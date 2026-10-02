import { useEffect, useState } from 'react'
import { getDaily, type DailyData, type DailyRow } from '../api/ops'
import { Banner, Empty, Skeleton, Status } from './ui'
import { fmtTime, localDate } from '../lib/format'

const FLAG: Record<string, { label: string; tone: 'ok' | 'risk' | 'bad' | 'neutral' }> = {
  no_show: { label: 'No-show', tone: 'bad' }, late: { label: 'Late', tone: 'risk' }, open: { label: 'Clocked in', tone: 'neutral' },
  missing_clock_out: { label: 'Missing clock-out', tone: 'bad' }, unrostered: { label: 'Not rostered', tone: 'risk' },
  excessive_hours: { label: 'Long day', tone: 'risk' }, outside_site: { label: 'Outside site', tone: 'bad' }, no_location: { label: 'No location', tone: 'risk' }, correction_pending: { label: 'Correction pending', tone: 'risk' },
}
const addDays = (date: string, n: number) => { const d = new Date(`${date}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }

/** The supervisor's daily list: who is late or absent, who is still in, what is missing, what nobody rostered. Computed live from shifts, punches and the site rules. */
export function AttendanceToday({ siteId, tz, onOpenTimesheets }: { siteId: string; tz: string; onOpenTimesheets: () => void }) {
  const [day, setDay] = useState(() => localDate(new Date(), tz))
  const [data, setData] = useState<DailyData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [only, setOnly] = useState<string>('exceptions')
  useEffect(() => { setData(null); setErr(null); getDaily(siteId, day).then(setData).catch((e) => setErr(e.message)) }, [siteId, day])
  const t = (iso: string | null) => (iso ? fmtTime(iso, tz) : '—')
  const rows = (data?.rows ?? []).filter((r) => only === 'all' || r.flags.length > 0)
  const counts = data?.counts ?? {}
  return (
    <>
      <div className="tp-row" style={{ marginBottom: 12 }}>
        <button className="tp-btn" onClick={() => setDay(addDays(day, -1))} aria-label="Previous day">←</button>
        <input type="date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} aria-label="Day" />
        <button className="tp-btn" onClick={() => setDay(localDate(new Date(), tz))}>Today</button>
        <button className="tp-btn" onClick={() => setDay(addDays(day, 1))} aria-label="Next day">→</button>
        <div className="tp-seg" role="group" aria-label="Rows" style={{ marginLeft: 'auto' }}>
          <button aria-pressed={only === 'exceptions'} onClick={() => setOnly('exceptions')}>Needs attention</button>
          <button aria-pressed={only === 'all'} onClick={() => setOnly('all')}>Everyone</button>
        </div>
      </div>
      {err && <Banner tone="bad" title="Could not load the daily list">{err}</Banner>}
      <section className="tp-kpis">
        {(['no_show', 'late', 'open', 'missing_clock_out', 'unrostered', 'excessive_hours'] as const).map((k) => (
          <div key={k} className="tp-card tp-kpi"><div className="lbl">{FLAG[k].label}</div>{data ? <div className="val">{counts[k] ?? 0}</div> : <Skeleton h={26} w={50} />}</div>))}
      </section>
      <section className="tp-card">
        {!data ? <div className="tp-body"><Skeleton h={180} /></div> : rows.length === 0 ? <Empty title={only === 'all' ? 'Nobody rostered or clocked in' : 'Nothing needs attention'}>Rostered shifts that start on this day, and any attendance, appear here.</Empty> : (
          <div style={{ overflow: 'auto', maxHeight: 560 }}>
            <table className="tp-table tp-num">
              <thead><tr><th>Worker</th><th>Rostered</th><th>Clocked in</th><th>Clocked out</th><th>Worked h</th><th>Flags</th></tr></thead>
              <tbody>{rows.map((r: DailyRow, i) => (
                <tr key={(r.session_id ?? r.worker_id) + i}>
                  <td>{r.label}<div className="tp-muted" style={{ fontSize: 12 }}>{r.role ?? 'no rostered shift'}</div></td>
                  <td>{r.scheduled_start ? `${t(r.scheduled_start)} → ${t(r.scheduled_end)}` : '—'}</td>
                  <td>{t(r.clock_in)}{r.minutes_late ? <div className="tp-muted" style={{ fontSize: 12 }}>{r.minutes_late} min late</div> : null}</td>
                  <td>{r.session_id && !r.clock_out ? (r.state === 'closed' ? 'closed by correction' : r.state === 'on_break' ? 'on break' : 'still in') : t(r.clock_out)}</td>
                  <td>{r.session_id ? r.worked_hours.toFixed(2) : '—'}</td>
                  <td className="tp-row" style={{ flexWrap: 'wrap' }}>{r.flags.length === 0 ? <Status tone="ok">OK</Status> : r.flags.map((f) => <Status key={f} tone={FLAG[f]?.tone ?? 'neutral'}>{FLAG[f]?.label ?? f}</Status>)}</td>
                </tr>))}</tbody>
            </table>
          </div>
        )}
      </section>
      <p className="tp-muted" style={{ fontSize: 12 }}>
        Late means more than {data?.policy.late_grace_minutes ?? 5} min after the rostered start; a clock-out is “missing” after {data?.policy.missing_punch_after_hours ?? 14} h; a long day is {data?.policy.excessive_hours ?? 12} h or more
        {data?.policy.is_default ? ' (these are Tempo’s defaults — set the site’s rules under Rules)' : ''}. To fix a missing clock-out or add a missing shift, use <button className="tp-btn" onClick={onOpenTimesheets}>Timesheets</button>.
      </p>
    </>
  )
}
