import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { getOverview, type ExceptionItem, type HourPoint } from '../api/ops'
import { useSite } from '../components/AppShell'
import { CoverageHeatmap, DemandCapacityChart } from '../components/charts'
import { Banner, Drawer, Empty, FreshnessBanner, KIND_LABEL, KpiCard, PageHead, Skeleton, SourcePills, STATE_LABEL, Status, severityTone } from '../components/ui'
import { SetupChecklist } from '../components/SetupChecklist'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { fmtAge, fmtDay, fmtNum, fmtTime, localDate } from '../lib/format'

export default function OverviewPage() {
  const { can } = useTempoContext()
  const { site } = useSite()
  const [params, setParams] = useSearchParams()
  const date = params.get('date') ?? undefined
  const nav = useNavigate()
  const [tick, setTick] = useState(0)
  const [picked, setPicked] = useState<ExceptionItem | null>(null)
  const [hour, setHour] = useState<HourPoint | null>(null)
  const q = useApi(() => (site ? getOverview(site.site_id, date) : Promise.resolve(null)), [site?.site_id, date, tick])
  useEffect(() => { const t = setInterval(() => setTick((n) => n + 1), 60000); return () => clearInterval(t) }, [])
  const ov = q.data
  const tz = ov?.site.timezone ?? site?.timezone ?? 'UTC'
  const kpi = (key: string) => ov?.kpis.find((x) => x.key === key)
  const labourGap = ov ? ov.hourly.reduce((sum, h) => sum + ((h.staffed_hours ?? 0) - (h.required_hours ?? h.staffed_hours ?? 0)), 0) : null
  const shortageHours = ov ? ov.heatmap.cells.filter((c) => c.status === 'shortage').reduce((sum, c) => sum + Math.max(0, c.required_hours - c.staffed_hours), 0) : 0
  const coverageCells = ov?.heatmap.cells.filter((c) => c.status !== 'no_demand') ?? []
  const coveredPct = coverageCells.length ? Math.round((coverageCells.filter((c) => c.status === 'covered').length / coverageCells.length) * 100) : null
  const liveSources = ov?.data_sources.filter((s) => s.mode === 'live' && s.fresh).length ?? 0
  const sourcePct = ov?.data_sources.length ? Math.round((liveSources / ov.data_sources.length) * 100) : null
  const nextRoster = ov?.roster_preview.find((r) => r.state !== 'published') ?? ov?.roster_preview[0]
  const topException = ov?.attention.find((e) => e.severity === 'critical' || e.severity === 'high') ?? ov?.attention[0]
  const bestMove = ov?.recommendations.find((r) => !r.stale) ?? ov?.recommendations[0]
  const actionTitle = topException ? `${KIND_LABEL[topException.kind] ?? topException.kind}${topException.worker_label ? ` · ${topException.worker_label}` : ''}` : bestMove ? bestMove.title : nextRoster ? `${nextRoster.label} roster is ${nextRoster.state}` : 'No action queued'
  const readiness = ov ? Math.round(((sourcePct ?? 0) * 0.35) + ((coveredPct ?? 0) * 0.35) + ((ov.attention.length === 0 ? 100 : Math.max(0, 100 - ov.attention.length * 18)) * 0.30)) : 0

  if (!site) return <Empty title="No site available">You have no site grants. Ask an administrator to grant access.</Empty>
  return (
    <>
      <PageHead
        title={`Today at ${site.name}`}
        sub={<>{tz} · <span className="tp-num">{ov ? `last refreshed ${fmtTime(ov.as_of, tz, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}` : 'loading…'}</span></>}
      >
        <label className="tp-field">Date
          <input type="date" value={date ?? (ov?.day ?? localDate(new Date(), tz))} onChange={(e) => { const p = new URLSearchParams(params); p.set('date', e.target.value); setParams(p, { replace: true }) }} />
        </label>
        <button className="tp-btn" onClick={() => setTick((n) => n + 1)}>Refresh</button>
      </PageHead>
      {can('labour.data.import') && <SetupChecklist compact />}

      {ov && <div style={{ marginBottom: 12 }}><SourcePills sources={ov.data_sources} /></div>}
      {ov && <FreshnessBanner sources={ov.data_sources} attendanceVerified={ov.attendance_verified} />}
      {q.error ? <Banner tone="bad" title="Overview could not be loaded">{String((q.error as Error).message)}</Banner> : null}

      <section className="tp-command" aria-label="Site command centre">
        <div className="tp-command-main">
          <div className="tp-row" style={{ justifyContent: 'space-between' }}>
            <div>
              <div className="tp-muted">Site command centre</div>
              <h2>{!ov ? 'Building today’s operating picture…' : `${site.name} is ${ov.attention.length ? 'carrying open exceptions' : 'clear for the current view'}`}</h2>
            </div>
            {ov && <Status tone={readiness >= 85 ? 'ok' : readiness >= 65 ? 'risk' : 'bad'}>{readiness}% ready</Status>}
          </div>
          <div className="tp-command-grid">
            <div className="tp-command-metric">
              <div className="lbl">Labour gap today</div>
              <div className="val">{labourGap == null ? '—' : `${labourGap >= 0 ? '+' : ''}${fmtNum(labourGap, 1)} h`}</div>
              <div className="meta">staffed minus required hours</div>
            </div>
            <div className="tp-command-metric">
              <div className="lbl">Coverage confidence</div>
              <div className="val">{coveredPct == null ? 'No forecast' : `${coveredPct}%`}</div>
              <div className="meta">{shortageHours > 0 ? `${fmtNum(shortageHours, 1)} h short across zones` : 'published roster vs demand'}</div>
            </div>
            <div className="tp-command-metric">
              <div className="lbl">Data confidence</div>
              <div className="val">{sourcePct == null ? '—' : `${sourcePct}%`}</div>
              <div className="meta">{ov?.attendance_verified === false ? 'presence not verified live' : 'fresh live sources'}</div>
            </div>
          </div>
          <div className="tp-row">
            {kpi('payable_hours') && <Status tone="neutral">Payable {kpi('payable_hours')!.display}</Status>}
            {kpi('forecast_wape') && <Status tone="neutral">Forecast error {kpi('forecast_wape')!.display}</Status>}
            {ov?.forecast.method && <span className="tp-muted">{ov.forecast.method}</span>}
          </div>
        </div>
        <div className="tp-action-card">
          <div className="tp-row" style={{ justifyContent: 'space-between' }}>
            <h2>Next best action</h2>
            {topException ? <Status tone={severityTone(topException.severity)}>{topException.severity}</Status> : bestMove?.stale ? <Status tone="risk">Expired</Status> : <Status tone="ok">Ready</Status>}
          </div>
          <div className="primary-line">{!ov ? 'Loading action queue…' : actionTitle}</div>
          <p className="tp-muted" style={{ margin: 0 }}>
            {topException ? `${STATE_LABEL[topException.state] ?? topException.state} · open for ${fmtAge(topException.age_seconds)} · detected after ${fmtAge(topException.detection_lag_seconds)}.`
              : bestMove ? `Recommended move set from optimisation run ${bestMove.run_id.slice(-6)}; backlog remaining ${fmtNum(bestMove.impact.remaining_backlog, 0)}.`
              : nextRoster ? `${nextRoster.shifts} shifts · ${nextRoster.workers} workers · ${nextRoster.approval ?? 'approval not recorded'}.`
              : 'No exception, recommendation or roster publication task is queued for this view.'}
          </p>
          <div className="tp-meter" aria-hidden="true"><span style={{ width: `${readiness}%` }} /></div>
          <div className="tp-row">
            {topException ? <button className="tp-btn primary" onClick={() => setPicked(topException)}>Open case</button>
              : bestMove ? <button className="tp-btn primary" onClick={() => nav(`/runs/${bestMove.run_id}?site=${site.site_id}`)}>Review move</button>
              : <Link className="tp-btn primary" style={{ textDecoration: 'none' }} to={`/roster?site=${site.site_id}`}>Open roster</Link>}
            <Link className="tp-btn" style={{ textDecoration: 'none' }} to={`/reports?site=${site.site_id}`}>View insights</Link>
          </div>
        </div>
      </section>

      <section className="tp-kpis" aria-label="Key figures">
        {!ov ? Array.from({ length: 6 }).map((_, i) => <div key={i} className="tp-card tp-kpi"><Skeleton h={12} w="60%" /><Skeleton h={28} w="50%" /><Skeleton h={10} w="70%" /></div>) : ov.kpis.map((k) => <KpiCard key={k.key} k={k} />)}
      </section>

      <div className="tp-grid">
        <div className="tp-stack">
          <section className="tp-card" aria-labelledby="h-chart">
            <header><h2 id="h-chart">Demand vs staffed capacity — units per hour, {ov?.day ?? '…'}</h2>
              <span className="tp-muted" style={{ fontSize: 12 }}>{ov?.forecast.method ?? ''}</span></header>
            <div className="tp-body">
              {!ov ? <Skeleton h={300} /> : <DemandCapacityChart data={ov.hourly} tz={tz} onPick={(h) => setHour(h)} />}
              {ov && !ov.forecast.run_id && <p className="tp-muted">No forecast run exists for this site yet, so the forecast line and band are not drawn.</p>}
            </div>
          </section>

          <section className="tp-card" aria-labelledby="h-heat">
            <header><h2 id="h-heat">Coverage by zone and shift</h2><span className="tp-muted" style={{ fontSize: 12 }}>planned, {ov?.day ?? ''}</span></header>
            <div className="tp-body">{!ov ? <Skeleton h={220} /> : <CoverageHeatmap heatmap={ov.heatmap} tz={tz} />}</div>
          </section>

          <section className="tp-card" aria-labelledby="h-prev">
            <header><h2 id="h-prev">Roster preview</h2><Link to={`/roster?site=${site.site_id}`}>Open Roster Planner →</Link></header>
            <div className="tp-body tp-row" style={{ gap: 12 }}>
              {!ov ? <Skeleton h={48} /> : ov.roster_preview.map((r) => (
                <div key={r.date} className="tp-card" style={{ padding: 12, minWidth: 220, flex: 1 }}>
                  <b>{r.label}</b> <span className="tp-muted">{fmtDay(`${r.date}T12:00:00Z`, 'UTC')}</span>
                  <div className="tp-num" style={{ margin: '6px 0' }}>{r.shifts} shifts · {r.workers} workers</div>
                  {r.state === 'published' ? <Status tone="ok">Published{r.approval ? ` · ${r.approval}` : ''}</Status> : r.state === 'draft' ? <Status tone="risk">Draft — not published</Status> : <Status tone="bad">No roster</Status>}
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="tp-stack">
          <section className="tp-card" aria-labelledby="h-att">
            <header><h2 id="h-att">Attention now</h2><Link to={`/live?site=${site.site_id}`}>All →</Link></header>
            {!ov ? <div className="tp-body"><Skeleton h={120} /></div> : ov.attention.length === 0 ? <Empty title="Nothing needs attention">No open exceptions at this site.</Empty> : (
              <ul className="tp-list">
                {ov.attention.map((e) => (
                  <li key={e.id}>
                    <button className="tp-item" onClick={() => setPicked(e)} aria-label={`${KIND_LABEL[e.kind] ?? e.kind}, ${e.severity}, ${e.worker_label ?? ''}, open for ${fmtAge(e.age_seconds)}`}>
                      <Status tone={severityTone(e.severity)}>{e.severity}</Status>
                      <span><span className="t">{KIND_LABEL[e.kind] ?? e.kind}</span><br /><span className="s">{e.worker_label ?? 'Site-level'} · {fmtAge(e.age_seconds)} · {e.owner_user_id ? 'owned' : 'unassigned'}</span></span>
                      <span aria-hidden="true">›</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="tp-card" aria-labelledby="h-rec">
            <header><h2 id="h-rec">Recommended moves</h2></header>
            {!ov ? <div className="tp-body"><Skeleton h={80} /></div> : ov.recommendations.length === 0 ? <Empty title="No recommendation right now">Recommendations appear when a run produces one from live backlog.</Empty> : (
              <ul className="tp-list">
                {ov.recommendations.map((r) => (
                  <li key={r.recommendation_id} className="tp-item" style={{ gridTemplateColumns: '1fr', cursor: 'default' }}>
                    <span className="t">{r.title}</span>
                    <span className="s">{r.moves.map((m) => `${m.from_zone} → ${m.to_zone}`).join(', ') || 'No moves'}</span>
                    <span className="s tp-num">Backlog remaining {fmtNum(r.impact.remaining_backlog, 0)}{r.stale ? ' · expired' : ''}</span>
                    <button className="tp-btn" onClick={() => nav(`/runs/${r.run_id}?site=${site.site_id}`)}>Review recommendation</button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>

      {picked && (
        <Drawer title={`${KIND_LABEL[picked.kind] ?? picked.kind}`} onClose={() => setPicked(null)}>
          <dl className="tp-dl">
            <dt>Severity</dt><dd><Status tone={severityTone(picked.severity)}>{picked.severity}</Status></dd>
            <dt>State</dt><dd>{STATE_LABEL[picked.state] ?? picked.state}</dd>
            <dt>Worker</dt><dd>{picked.worker_label ?? '—'}</dd>
            <dt>Occurred</dt><dd>{fmtTime(picked.source_occurred_at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}</dd>
            <dt>Detected</dt><dd>{fmtTime(picked.detected_at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })} (lag {fmtAge(picked.detection_lag_seconds)})</dd>
            <dt>Evidence</dt><dd><pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'var(--tp-font-mono)', fontSize: 12 }}>{JSON.stringify(picked.evidence, null, 2)}</pre></dd>
          </dl>
          <p><Link className="tp-btn primary" style={{ textDecoration: 'none', display: 'inline-block' }} to={`/live?site=${site.site_id}&case=${picked.id}`}>Open resolve path in Live Operations</Link></p>
        </Drawer>
      )}
      {hour && (
        <Drawer title="Demand detail" onClose={() => setHour(null)}>
          <dl className="tp-dl">
            <dt>Hour</dt><dd>{fmtTime(hour.hour_start, tz)}</dd>
            <dt>Actual units</dt><dd className="tp-num">{fmtNum(hour.actual_units)}</dd>
            <dt>Forecast</dt><dd className="tp-num">{fmtNum(hour.forecast_units)} ({fmtNum(hour.forecast_lower)}–{fmtNum(hour.forecast_upper)})</dd>
            <dt>Required hours</dt><dd className="tp-num">{fmtNum(hour.required_hours, 1)}</dd>
            <dt>Staffed hours</dt><dd className="tp-num">{fmtNum(hour.staffed_hours, 1)}</dd>
            <dt>Source</dt><dd>{hour.source.actual}{hour.source.forecast ? ` · forecast ${hour.source.forecast}` : ''}</dd>
          </dl>
          <p className="tp-muted">The Demand workspace (assumptions, work standards, overrides) is not built yet.</p>
        </Drawer>
      )}
    </>
  )
}
