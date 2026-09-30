import { useMemo, useState } from 'react'
import type { HeatCell, HourPoint, Overview } from '../api/ops'
import { fmtNum, fmtTime, localHour } from '../lib/format'

const W = 860, H = 300, PL = 46, PR = 16, PT = 14, PB = 30

/**
 * Hourly demand vs capacity. Actual = solid line, forecast = dashed line + band, staffed capacity = stepped line.
 * Every point is keyboard-reachable; a table alternative is available; missing values leave gaps (never zero).
 */
export function DemandCapacityChart({ data, tz, onPick }: { data: HourPoint[]; tz: string; onPick?: (h: HourPoint) => void }) {
  const [active, setActive] = useState<number | null>(null)
  const [table, setTable] = useState(false)
  const max = useMemo(() => Math.max(1, ...data.flatMap((d) => [d.actual_units ?? 0, d.forecast_upper ?? 0, d.capacity_units ?? 0])) * 1.08, [data])
  const x = (i: number) => PL + (i + 0.5) * ((W - PL - PR) / Math.max(1, data.length))
  const y = (v: number) => PT + (1 - v / max) * (H - PT - PB)
  const bw = (W - PL - PR) / Math.max(1, data.length)
  const line = (get: (d: HourPoint) => number | null) => {
    let d = '', pen = false
    data.forEach((p, i) => { const v = get(p); if (v == null) { pen = false; return } d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`; pen = true })
    return d
  }
  const step = () => {
    let d = ''
    data.forEach((p, i) => { if (p.capacity_units == null) return; const x0 = PL + i * bw, x1 = x0 + bw; d += `${d ? 'L' : 'M'}${x0.toFixed(1)},${y(p.capacity_units).toFixed(1)}L${x1.toFixed(1)},${y(p.capacity_units).toFixed(1)}` })
    return d
  }
  const band = () => {
    const pts = data.map((p, i) => ({ i, lo: p.forecast_lower, hi: p.forecast_upper })).filter((p) => p.lo != null && p.hi != null)
    if (pts.length < 2) return ''
    return `M${pts.map((p) => `${x(p.i).toFixed(1)},${y(p.hi!).toFixed(1)}`).join('L')}L${[...pts].reverse().map((p) => `${x(p.i).toFixed(1)},${y(p.lo!).toFixed(1)}`).join('L')}Z`
  }
  const now = data.findIndex((d, i) => d.actual_units == null && i > 0 && data[i - 1].actual_units != null)
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * max)
  const a = active != null ? data[active] : null
  const hasAny = data.some((d) => d.actual_units != null || d.forecast_units != null || d.capacity_units != null)
  if (!hasAny) return <div className="tp-empty" role="status"><b>No demand or capacity data for this day</b>Nothing is drawn rather than a zero line.</div>
  return (
    <div style={{ position: 'relative' }}>
      <div className="tp-row" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
        <div className="tp-legend" aria-hidden="true">
          <span><i style={{ borderColor: 'var(--tp-chart-actual)' }} />Actual received (units/h)</span>
          <span><i style={{ borderColor: 'var(--tp-chart-forecast)', borderTopStyle: 'dashed' }} />Forecast &amp; 90% band</span>
          <span><i style={{ borderColor: 'var(--tp-chart-capacity)' }} />Staffed capacity (units/h)</span>
        </div>
        <button className="tp-btn" onClick={() => setTable(!table)} aria-pressed={table}>{table ? 'Show chart' : 'Show data table'}</button>
      </div>
      {table ? (
        <div style={{ maxHeight: 320, overflow: 'auto' }}>
          <table className="tp-table tp-num">
            <caption className="tp-sr-only">Hourly demand versus capacity</caption>
            <thead><tr><th>Hour</th><th>Actual</th><th>Forecast</th><th>Band</th><th>Capacity</th><th>Required h</th><th>Staffed h</th></tr></thead>
            <tbody>{data.map((d) => (<tr key={d.hour_start}><td>{fmtTime(d.hour_start, tz)}</td><td>{fmtNum(d.actual_units)}</td><td>{fmtNum(d.forecast_units)}</td><td>{d.forecast_lower != null ? `${fmtNum(d.forecast_lower)}–${fmtNum(d.forecast_upper)}` : '—'}</td><td>{fmtNum(d.capacity_units)}</td><td>{fmtNum(d.required_hours, 1)}</td><td>{fmtNum(d.staffed_hours, 1)}</td></tr>))}</tbody>
          </table>
        </div>
      ) : (
        <svg className="tp-chart" viewBox={`0 0 ${W} ${H}`} role="group" aria-label="Hourly demand versus staffed capacity chart. Use Tab to move between hours, or open the data table.">
          <title>Hourly demand (units per hour) versus staffed capacity, local time</title>
          {ticks.map((t) => (<g key={t}><line x1={PL} x2={W - PR} y1={y(t)} y2={y(t)} stroke="var(--tp-chart-grid)" /><text x={PL - 6} y={y(t) + 4} textAnchor="end">{fmtNum(t)}</text></g>))}
          {data.map((d, i) => (i % 3 === 0 ? <text key={d.hour_start} x={x(i)} y={H - 10} textAnchor="middle">{String(localHour(d.hour_start, tz)).padStart(2, '0')}:00</text> : null))}
          <path d={band()} fill="var(--tp-chart-band)" />
          <path d={line((d) => d.forecast_units)} fill="none" stroke="var(--tp-chart-forecast)" strokeWidth="2" strokeDasharray="6 4" />
          <path d={step()} fill="none" stroke="var(--tp-chart-capacity)" strokeWidth="2.5" />
          <path d={line((d) => d.actual_units)} fill="none" stroke="var(--tp-chart-actual)" strokeWidth="2.5" />
          {now > 0 && <g><line x1={PL + now * bw} x2={PL + now * bw} y1={PT} y2={H - PB} stroke="var(--tp-red)" strokeWidth="1.5" strokeDasharray="2 3" /><text x={PL + now * bw + 4} y={PT + 10}>now</text></g>}
          {data.map((d, i) => (
            <rect key={d.hour_start} x={PL + i * bw} y={PT} width={bw} height={H - PT - PB} fill="transparent" tabIndex={0}
              aria-label={`${fmtTime(d.hour_start, tz)}: actual ${d.actual_units != null ? fmtNum(d.actual_units) : 'none yet'}, forecast ${d.forecast_units != null ? fmtNum(d.forecast_units) : 'none'}, capacity ${d.capacity_units != null ? fmtNum(d.capacity_units) : 'none'} units`}
              onMouseEnter={() => setActive(i)} onFocus={() => setActive(i)} onMouseLeave={() => setActive(null)} onBlur={() => setActive(null)}
              onClick={() => onPick?.(d)} onKeyDown={(e) => { if (e.key === 'Enter') onPick?.(d) }} style={{ cursor: onPick ? 'pointer' : 'default' }} />
          ))}
          {a && active != null && <line x1={x(active)} x2={x(active)} y1={PT} y2={H - PB} stroke="var(--tp-line-strong)" />}
        </svg>
      )}
      {a && !table && active != null && (
        <div className="tp-tip" role="tooltip" style={{ left: `${Math.min(70, Math.max(2, (x(active) / W) * 100 - 8))}%`, top: 44 }}>
          <b>{fmtTime(a.hour_start, tz)}–{fmtTime(new Date(new Date(a.hour_start).getTime() + 3600e3).toISOString(), tz)}</b>
          <div className="tp-num">Actual: {a.actual_units != null ? `${fmtNum(a.actual_units)} units` : 'not yet received'}</div>
          <div className="tp-num">Forecast: {a.forecast_units != null ? `${fmtNum(a.forecast_units)} (${fmtNum(a.forecast_lower)}–${fmtNum(a.forecast_upper)})` : 'none'}</div>
          <div className="tp-num">Capacity: {a.capacity_units != null ? fmtNum(a.capacity_units) : 'no roster'} · {fmtNum(a.staffed_hours, 1)} staffed h / {a.required_hours != null ? fmtNum(a.required_hours, 1) : '—'} req h</div>
          <div>Source: {a.source.actual}{a.source.forecast ? ` · forecast ${a.source.forecast}` : ''}</div>
        </div>
      )}
    </div>
  )
}

const CELL_ICON: Record<HeatCell['status'], string> = { covered: '✓', risk: '▲', shortage: '✕', no_demand: '–' }

export function CoverageHeatmap({ heatmap, tz }: { heatmap: Overview['heatmap']; tz: string }) {
  const { zones, shifts, cells } = heatmap
  if (!zones.length || !shifts.length) return <div className="tp-empty" role="status"><b>No shifts published for this day</b>Coverage needs a published roster and a forecast.</div>
  const by = new Map(cells.map((c) => [`${c.zone}|${c.shift}`, c]))
  return (
    <div>
      <div className="tp-heat" style={{ gridTemplateColumns: `120px repeat(${shifts.length}, minmax(0,1fr))` }} role="table" aria-label="Coverage by zone and shift">
        <div />
        {shifts.map((s) => (<div key={s.code} className="tp-head" role="columnheader">{fmtTime(s.start, tz)}–{fmtTime(s.end, tz)}</div>))}
        {zones.map((z) => (
          <div key={z.zone_id} style={{ display: 'contents' }} role="row">
            <div className="tp-head" role="rowheader" style={{ alignSelf: 'center' }}>{z.name}</div>
            {shifts.map((s) => {
              const c = by.get(`${z.zone_id}|${s.code}`)
              if (!c) return <div key={s.code} className="tp-cell no_demand" role="cell">–</div>
              return (
                <div key={s.code} className={`tp-cell ${c.status}`} role="cell" tabIndex={0}
                  aria-label={`${z.name}, ${fmtTime(s.start, tz)} shift: ${c.label}. ${c.staffed_hours} staffed hours of ${c.required_hours} required`}>
                  <b><span aria-hidden="true">{CELL_ICON[c.status]}</span>{c.label}</b>
                  <span className="tp-num">{c.staffed_hours} / {c.required_hours} h</span>
                </div>
              )
            })}
          </div>
        ))}
      </div>
      <div className="tp-legend" style={{ marginTop: 8 }}><span>✓ Covered (≥100%)</span><span>▲ At risk (85–99%)</span><span>✕ Shortage (&lt;85%)</span><span>– No demand</span><span className="tp-muted">staffed hours / required hours</span></div>
    </div>
  )
}
