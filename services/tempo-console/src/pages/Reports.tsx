import { Link } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { getVariance, type Variance } from '../api/ops'
import { useSite } from '../components/AppShell'
import { useTempoContext } from '../context/TempoContextProvider'
import { exportCsv } from '../api/ops'
import { Banner, ExportButton, Empty, FreshnessBanner, PageHead, Skeleton, SourcePills, Status } from '../components/ui'
import { fmtMoney, fmtNum, fmtTime, localDate } from '../lib/format'

const addDays = (date: string, n: number) => { const d = new Date(`${date}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const mondayOf = (date: string) => { const d = new Date(`${date}T00:00:00Z`); return addDays(date, -((d.getUTCDay() + 6) % 7)) }

export default function ReportsPage() {
  const { site } = useSite()
  const { can } = useTempoContext()
  const tz = site?.timezone ?? 'UTC'
  const [start, setStart] = useState(() => mondayOf(localDate(new Date(), tz)))
  const [v, setV] = useState<Variance | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [help, setHelp] = useState<string | null>(null)
  useEffect(() => { setV(null); if (site) getVariance(site.site_id, start).then(setV).catch((e) => setErr(e.message)) }, [site, start])
  if (!site) return <Empty title="No site available" />
  const t = v?.totals
  const rates = t && 'planned_cost' in t
  const tile = (key: string, label: string, val: string, sub: string, tone?: 'estimate' | 'confirmed') => (
    <div className="tp-card tp-kpi" key={key}><div className="lbl">{label}<button className="tp-info" aria-label={`Definition of ${label}`} onClick={() => setHelp(help === key ? null : key)}>i</button></div>
      <div className="val">{val}</div><div className="meta">{tone && <Status tone={tone === 'confirmed' ? 'ok' : 'risk'}>{tone}</Status>} {sub}</div>
      {help === key && <div className="tp-pop">{v?.definitions[key] ?? ''}</div>}</div>
  )
  return (
    <>
      <PageHead title="Insights & Reports — plan vs actual" sub={`${site.name} · week of ${start} · ${v?.metric_version ?? ''}`}>
        {can('labour.export') && site && <ExportButton run={() => exportCsv(site.site_id, 'variance', start)} />}
        <div className="tp-row"><button className="tp-btn" onClick={() => setStart(addDays(start, -7))} aria-label="Previous week">←</button><button className="tp-btn" onClick={() => setStart(mondayOf(localDate(new Date(), tz)))}>This week</button><button className="tp-btn" onClick={() => setStart(addDays(start, 7))} aria-label="Next week">→</button></div>
      </PageHead>
      {err && <Banner tone="bad" title="Could not load the report">{err}</Banner>}
      {v && <div style={{ marginBottom: 12 }}><SourcePills sources={v.data_sources} /></div>}
      {v && <FreshnessBanner sources={v.data_sources} attendanceVerified={v.attendance_verified} />}
      <section className="tp-kpis" aria-label="Week totals">
        {!t ? Array.from({ length: 6 }).map((_, i) => <div key={i} className="tp-card tp-kpi"><Skeleton h={12} w="60%" /><Skeleton h={26} w="50%" /></div>) : <>
          {tile('scheduled_hours', 'Scheduled hours', fmtNum(t.scheduled_hours as number, 1), 'published roster, to date')}
          {tile('attended_hours', 'Attended hours', fmtNum(t.attended_hours as number, 1), `variance ${(t.variance_hours as number) >= 0 ? '+' : ''}${fmtNum(t.variance_hours as number, 1)} h`, 'estimate')}
          {tile('payable_hours', 'Payable hours', fmtNum(t.payable_hours as number, 1), `${fmtNum(t.unconfirmed_hours as number, 1)} h awaiting approval`, 'confirmed')}
          {tile('adherence', 'Roster adherence', t.adherence_pct == null ? 'No verified data' : `${t.adherence_pct}%`, 'matched attended ÷ due shifts')}
          {tile('forecast_wape', 'Forecast error (WAPE)', t.forecast_wape_pct == null ? 'No verified data' : `${t.forecast_wape_pct}%`, `${t.forecast_days_scored} completed day(s) scored`)}
          {rates && tile('confirmed_cost', 'Cost — plan / est. actual', `${fmtMoney(t.planned_cost as number)} / ${fmtMoney(t.estimated_actual_cost as number)}`, `confirmed so far ${fmtMoney(t.confirmed_cost as number)}`, 'estimate')}
        </>}
      </section>
      <section className="tp-card"><header><h2>By day</h2><span className="tp-muted" style={{ fontSize: 12 }}>attended = estimate · payable = approved timesheets only</span></header>
        {!v ? <div className="tp-body"><Skeleton h={220} /></div> : (
          <div style={{ overflow: 'auto' }}><table className="tp-table tp-num">
            <thead><tr><th>Day</th><th>Sched. h</th><th>Attended h</th><th>Payable h</th><th>Variance h</th><th>Adherence</th><th>Late</th><th>No-shows</th><th>OT h</th><th>Forecast</th><th>Actual</th><th>Forecast error</th>{rates && <><th>Plan $</th><th>Est. actual $</th><th>Confirmed $</th></>}</tr></thead>
            <tbody>{v.days.map((r) => {
              const nd = r.status === 'upcoming'  // nothing has happened yet: dashes, never zeros
              const n1 = (x: number) => (nd ? '—' : fmtNum(x, 1))
              const m = (x: number | undefined) => (nd ? '—' : fmtMoney(x))
              return (
              <tr key={r.date}><td><Link to={`/attendance?view=today&date=${r.date}`} title="See who was late, absent or missing a clock-out that day">{fmtTime(`${r.date}T12:00:00Z`, 'UTC', { weekday: 'short', day: '2-digit', month: 'short' })}</Link>{r.status !== 'complete' && <span className="tp-muted"> · {r.status === 'upcoming' ? 'upcoming' : 'in progress'}</span>}</td>
                <td>{n1(r.scheduled_hours)}</td><td>{n1(r.attended_hours)}</td><td>{n1(r.payable_hours)}</td>
                <td>{nd ? '—' : `${r.variance_hours > 0 ? '+' : ''}${fmtNum(r.variance_hours, 1)}`}</td><td>{r.adherence_pct != null ? `${r.adherence_pct}%` : '—'}</td><td>{r.late ?? '—'}</td><td>{r.no_shows ?? '—'}</td><td>{n1(r.overtime_hours)}</td>
                <td>{fmtNum(r.forecast_units)}</td><td>{fmtNum(r.actual_units)}</td><td>{r.forecast_ape_pct != null ? `${r.forecast_ape_pct}%` : '—'}</td>
                {rates && <><td>{m(r.planned_cost)}</td><td>{m(r.estimated_actual_cost)}</td><td>{m(r.confirmed_cost)}</td></>}</tr>)})}</tbody>
          </table></div>
        )}
      </section>
      <p className="tp-muted" style={{ fontSize: 12.5 }}>{v?.notes.join(' ')} Forecast: {v?.forecast.method}. Productivity treats all attended time as productive (no exclusion policy configured).</p>
    </>
  )
}
