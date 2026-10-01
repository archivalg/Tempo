import { useEffect, useMemo, useState } from 'react'
import { getDemand, type Demand } from '../api/ops'
import { useSite } from '../components/AppShell'
import { useTempoContext } from '../context/TempoContextProvider'
import { exportCsv } from '../api/ops'
import { Banner, ExportButton, Empty, FreshnessBanner, PageHead, Skeleton, SourcePills, Status } from '../components/ui'
import { fmtNum, fmtTime, localDate } from '../lib/format'

const addDays = (date: string, n: number) => { const d = new Date(`${date}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10) }
const mondayOf = (date: string) => { const d = new Date(`${date}T00:00:00Z`); return addDays(date, -((d.getUTCDay() + 6) % 7)) }

export default function DemandPage() {
  const { site } = useSite()
  const { can } = useTempoContext()
  const tz = site?.timezone ?? 'UTC'
  const [start, setStart] = useState(() => mondayOf(localDate(new Date(), tz)))
  const [d, setD] = useState<Demand | null>(null)
  const [act, setAct] = useState('')
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { setD(null); if (site) getDemand(site.site_id, start).then(setD).catch((e) => setErr(e.message)) }, [site, start])

  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => addDays(start, i)), [start])
  const rows = (d?.rows ?? []).filter((r) => !act || r.activity === act)
  const byDay = days.map((day) => {
    const rs = rows.filter((r) => r.date === day)
    const sum = (k: 'actual_units' | 'forecast_units' | 'forecast_lower' | 'forecast_upper' | 'required_hours') => (rs.some((r) => r[k] != null) ? rs.reduce((a, r) => a + (r[k] ?? 0), 0) : null)
    return { day, actual: sum('actual_units'), forecast: sum('forecast_units'), lo: sum('forecast_lower'), hi: sum('forecast_upper'), req: sum('required_hours') }
  })
  const max = Math.max(1, ...byDay.flatMap((b) => [b.actual ?? 0, b.hi ?? 0])) * 1.1
  const W = 760, H = 240, PL = 52, PB = 28, PT = 10, bw = (W - PL - 10) / 7
  const y = (v: number) => PT + (1 - v / max) * (H - PT - PB)
  if (!site) return <Empty title="No site available" />
  return (
    <>
      <PageHead title="Demand" sub={`${site.name} · week of ${start} · units received vs forecast, and the labour hours they imply`}>
        <label className="tp-field">Activity<select value={act} onChange={(e) => setAct(e.target.value)}><option value="">All activities</option>{d?.activities.map((a) => <option key={a}>{a}</option>)}</select></label>
        {can('labour.export') && site && <ExportButton run={() => exportCsv(site.site_id, 'demand', start)} />}
        <div className="tp-row"><button className="tp-btn" onClick={() => setStart(addDays(start, -7))} aria-label="Previous week">←</button><button className="tp-btn" onClick={() => setStart(mondayOf(localDate(new Date(), tz)))}>This week</button><button className="tp-btn" onClick={() => setStart(addDays(start, 7))} aria-label="Next week">→</button></div>
      </PageHead>
      {err && <Banner tone="bad" title="Could not load demand">{err}</Banner>}
      {d && <div style={{ marginBottom: 12 }}><SourcePills sources={d.data_sources} /></div>}
      {d && <FreshnessBanner sources={d.data_sources} />}
      <div className="tp-grid">
        <div className="tp-stack">
          <section className="tp-card"><header><h2>Daily units — actual vs forecast</h2><span className="tp-muted" style={{ fontSize: 12 }}>{d?.forecast.method}</span></header>
            <div className="tp-body">
              {!d ? <Skeleton h={240} /> : (
                <svg className="tp-chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Daily actual and forecast units. A data table follows.">
                  {[0, .25, .5, .75, 1].map((f) => <g key={f}><line x1={PL} x2={W - 10} y1={y(max * f)} y2={y(max * f)} stroke="var(--tp-chart-grid)" /><text x={PL - 6} y={y(max * f) + 4} textAnchor="end">{fmtNum(max * f)}</text></g>)}
                  {byDay.map((b, i) => (<g key={b.day}>
                    {b.lo != null && b.hi != null && <rect x={PL + i * bw + bw * .12} width={bw * .76} y={y(b.hi)} height={Math.max(2, y(b.lo) - y(b.hi))} fill="var(--tp-chart-band)" stroke="var(--tp-chart-forecast)" strokeDasharray="4 3" />}
                    {b.actual != null && <rect x={PL + i * bw + bw * .3} width={bw * .4} y={y(b.actual)} height={H - PB - y(b.actual)} fill="var(--tp-chart-actual)" opacity=".85" />}
                    {b.forecast != null && <line x1={PL + i * bw + bw * .08} x2={PL + i * bw + bw * .92} y1={y(b.forecast)} y2={y(b.forecast)} stroke="var(--tp-chart-forecast)" strokeWidth="3" strokeDasharray="6 3" />}
                    <text x={PL + i * bw + bw / 2} y={H - 10} textAnchor="middle">{fmtTime(`${b.day}T12:00:00Z`, 'UTC', { weekday: 'short', day: '2-digit' })}</text>
                  </g>))}
                </svg>
              )}
              <div className="tp-legend"><span><i style={{ borderColor: 'var(--tp-chart-actual)' }} />Actual received</span><span><i style={{ borderColor: 'var(--tp-chart-forecast)', borderTopStyle: 'dashed' }} />Forecast (dashed) with 90% band</span></div>
            </div>
          </section>
          <section className="tp-card"><header><h2>By day</h2></header>
            {!d ? <div className="tp-body"><Skeleton h={160} /></div> : (
              <table className="tp-table tp-num"><thead><tr><th>Day</th><th>Actual units</th><th>Forecast</th><th>90% band</th><th>Error</th><th>Required hours</th></tr></thead><tbody>
                {byDay.map((b) => (<tr key={b.day}><td>{fmtTime(`${b.day}T12:00:00Z`, 'UTC', { weekday: 'short', day: '2-digit', month: 'short' })}</td><td>{fmtNum(b.actual)}</td><td>{fmtNum(b.forecast)}</td><td>{b.lo != null ? `${fmtNum(b.lo)}–${fmtNum(b.hi)}` : '—'}</td>
                  <td>{b.actual && b.forecast ? `${(((b.forecast - b.actual) / b.actual) * 100).toFixed(1)}%` : '—'}</td><td>{fmtNum(b.req, 1)}</td></tr>))}
              </tbody></table>
            )}
          </section>
        </div>
        <aside className="tp-stack">
          <section className="tp-card"><header><h2>Data readiness</h2></header>
            <ul className="tp-list">{!d ? <li className="tp-body"><Skeleton h={100} /></li> : d.readiness.map((r) => (<li key={r.check} className="tp-item" style={{ gridTemplateColumns: 'auto 1fr', cursor: 'default' }}><Status tone={r.ok ? 'ok' : 'bad'}>{r.ok ? 'Ready' : 'Not ready'}</Status><span><span className="t">{r.check}</span><br /><span className="s">{r.detail}</span></span></li>))}</ul>
          </section>
          <section className="tp-card"><header><h2>Work standards</h2></header>
            <div className="tp-body">{!d ? <Skeleton h={80} /> : <table className="tp-table tp-num"><thead><tr><th>Activity</th><th>s / unit</th><th>Role → zone</th></tr></thead><tbody>
              {d.standards.map((s) => (<tr key={s.activity}><td>{s.activity}</td><td>{s.seconds_per_unit}</td><td className="tp-muted">{d.zone_map.filter((m) => m.activity === s.activity).map((m) => `${m.role} → ${m.zone}`).join(', ') || '—'}</td></tr>))}
            </tbody></table>}</div>
          </section>
          <section className="tp-card"><header><h2>Forecast snapshot</h2></header>
            <div className="tp-body"><dl className="tp-dl" style={{ gridTemplateColumns: '110px 1fr' }}>
              <dt>Run</dt><dd style={{ wordBreak: 'break-all' }}>{d?.forecast.run_id ?? 'none'}</dd>
              <dt>Snapshot</dt><dd style={{ wordBreak: 'break-all' }}>{d?.forecast.snapshot_id ?? '—'}</dd>
              <dt>Method</dt><dd>{d?.forecast.method}</dd>
              <dt>Back-test MAPE</dt><dd>{d?.forecast.backtest_mape != null ? `${(d.forecast.backtest_mape * 100).toFixed(1)}%` : '—'}</dd>
            </dl><p className="tp-muted" style={{ fontSize: 12.5 }}>{d?.overrides_note} The forecast has no seasonal term, so weekday/weekend swings show as error.</p></div>
          </section>
        </aside>
      </div>
    </>
  )
}
