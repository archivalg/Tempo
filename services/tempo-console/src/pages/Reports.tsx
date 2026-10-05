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
  const completeDays = v?.days.filter((d) => d.status !== 'upcoming') ?? []
  const worstForecast = completeDays.filter((d) => d.forecast_ape_pct != null).sort((a, b) => (b.forecast_ape_pct ?? 0) - (a.forecast_ape_pct ?? 0))[0]
  const totalLate = completeDays.reduce((sum, d) => sum + (d.late ?? 0), 0)
  const totalNoShows = completeDays.reduce((sum, d) => sum + (d.no_shows ?? 0), 0)
  const avgProductivity = completeDays.length ? completeDays.reduce((sum, d) => sum + (d.productivity_units_per_hour ?? 0), 0) / completeDays.filter((d) => d.productivity_units_per_hour != null).length : null
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
      {v && (
        <section className="tp-insight-strip" aria-label="Report insights">
          <div className="tp-insight"><b>Forecast risk</b><div className="big">{worstForecast?.forecast_ape_pct != null ? `${worstForecast.forecast_ape_pct}%` : 'No verified data'}</div><span className="tp-muted">{worstForecast ? `largest daily error on ${fmtTime(`${worstForecast.date}T12:00:00Z`, 'UTC', { weekday: 'short', day: '2-digit' })}` : 'needs completed actual workload'}</span></div>
          <div className="tp-insight"><b>Attendance drag</b><div className="big">{totalLate + totalNoShows}</div><span className="tp-muted">{totalLate} late · {totalNoShows} no-shows</span></div>
          <div className="tp-insight"><b>Productivity</b><div className="big">{avgProductivity && Number.isFinite(avgProductivity) ? fmtNum(avgProductivity, 1) : 'No verified data'}</div><span className="tp-muted">actual units per attended hour</span></div>
          <div className="tp-insight"><b>Payroll readiness</b><div className="big">{fmtNum(t?.unconfirmed_hours as number | null, 1)} h</div><span className="tp-muted">awaiting approval before payroll export</span></div>
        </section>
      )}
      {v && (
        <div className="tp-grid" style={{ marginBottom: 16 }}>
          <section className="tp-card" aria-label="Variance trend">
            <header><h2>Labour variance trend</h2><span className="tp-muted" style={{ fontSize: 12 }}>scheduled vs attended vs payable</span></header>
            <div className="tp-body"><VarianceTrend days={v.days} /></div>
          </section>
          <aside className="tp-stack">
            <section className="tp-card" aria-label="Cost bridge">
              <header><h2>Cost bridge</h2>{rates ? <Status tone="risk">estimate</Status> : <Status tone="neutral">withheld</Status>}</header>
              <div className="tp-body">{rates ? <CostBridge totals={t!} /> : <p className="tp-muted">Rates are not available for this report, so cost comparisons are withheld.</p>}</div>
            </section>
            <section className="tp-card" aria-label="Exception concentration">
              <header><h2>Exception concentration</h2></header>
              <div className="tp-body"><ExceptionBars days={v.days} /></div>
            </section>
          </aside>
        </div>
      )}
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

function VarianceTrend({ days }: { days: Variance['days'] }) {
  const max = Math.max(1, ...days.flatMap((d) => [d.scheduled_hours, d.attended_hours, d.payable_hours]))
  const rows = days.map((d) => ({ ...d, label: fmtTime(`${d.date}T12:00:00Z`, 'UTC', { weekday: 'short' }) }))
  return (
    <div className="tp-mini-bars" role="img" aria-label="Daily scheduled, attended and payable hours">
      {rows.map((d) => (
        <div key={d.date} className="tp-mini-bar" style={{ gridTemplateColumns: '70px 1fr auto' }}>
          <span>{d.label}</span>
          <div className="track" title={`${d.scheduled_hours} scheduled, ${d.attended_hours} attended, ${d.payable_hours} payable`}>
            <span className="fill" style={{ display: 'block', width: `${(d.scheduled_hours / max) * 100}%`, background: 'var(--tp-chart-forecast)', opacity: .35 }} />
            <span className="fill" style={{ display: 'block', width: `${(d.attended_hours / max) * 100}%`, background: 'var(--tp-chart-capacity)', transform: 'translateY(-8px)' }} />
            <span className="fill" style={{ display: 'block', width: `${(d.payable_hours / max) * 100}%`, background: 'var(--tp-chart-actual)', transform: 'translateY(-16px)', height: 3 }} />
          </div>
          <span className="tp-num">{d.status === 'upcoming' ? '—' : `${d.variance_hours >= 0 ? '+' : ''}${fmtNum(d.variance_hours, 1)} h`}</span>
        </div>
      ))}
      <div className="tp-legend"><span><i style={{ borderColor: 'var(--tp-chart-forecast)' }} />Scheduled</span><span><i style={{ borderColor: 'var(--tp-chart-capacity)' }} />Attended estimate</span><span><i style={{ borderColor: 'var(--tp-chart-actual)' }} />Approved payable</span></div>
    </div>
  )
}

function CostBridge({ totals }: { totals: Record<string, number | null> }) {
  const planned = Number(totals.planned_cost ?? 0)
  const estimated = Number(totals.estimated_actual_cost ?? 0)
  const confirmed = Number(totals.confirmed_cost ?? 0)
  const max = Math.max(1, planned, estimated, confirmed)
  const rows: [string, number][] = [['Plan', planned], ['Estimated actual', estimated], ['Confirmed', confirmed]]
  return (
    <div className="tp-mini-bars">
      {rows.map(([label, val]) => (
        <div key={label} className="tp-mini-bar">
          <span>{label}</span><span className="track"><span className="fill" style={{ display: 'block', width: `${(val / max) * 100}%` }} /></span><span className="tp-num">{fmtMoney(val)}</span>
        </div>
      ))}
      <p className="tp-muted" style={{ margin: 0, fontSize: 12.5 }}>Confirmed cost only includes approved timesheets; estimated actual can move as attendance changes.</p>
    </div>
  )
}

function ExceptionBars({ days }: { days: Variance['days'] }) {
  const max = Math.max(1, ...days.map((d) => (d.late ?? 0) + (d.no_shows ?? 0)))
  return (
    <div className="tp-mini-bars">
      {days.map((d) => {
        const total = (d.late ?? 0) + (d.no_shows ?? 0)
        return (
          <div key={d.date} className="tp-mini-bar">
            <span>{fmtTime(`${d.date}T12:00:00Z`, 'UTC', { weekday: 'short' })}</span>
            <span className="track"><span className="fill" style={{ display: 'block', width: `${(total / max) * 100}%`, background: total ? 'var(--tp-amber)' : 'var(--tp-green)' }} /></span>
            <span className="tp-num">{total || '—'}</span>
          </div>
        )
      })}
    </div>
  )
}
