import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { acknowledgeException, assignException, detectExceptions, getLive, resolveException, type ExceptionItem, type Live, type LiveRow } from '../api/ops'
import { useSite } from '../components/AppShell'
import { Banner, Drawer, Empty, FreshnessBanner, KIND_LABEL, PageHead, Skeleton, SourcePills, STATE_LABEL, Status, severityTone, type Tone } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { fmtAge, fmtTime } from '../lib/format'

const STATE: Record<string, { tone: Tone; label: string }> = {
  present: { tone: 'ok', label: 'Present' }, late: { tone: 'risk', label: 'Late' }, absent: { tone: 'bad', label: 'Absent' }, unrostered: { tone: 'bad', label: 'Unrostered' },
  upcoming: { tone: 'neutral', label: 'Upcoming' }, awaiting: { tone: 'neutral', label: 'Awaiting' }, completed: { tone: 'neutral', label: 'Completed' }, unverified: { tone: 'risk', label: 'Unverified (source stale)' },
}
const COUNTS: { key: 'expected' | 'present' | 'absent' | 'late' | 'unrostered'; label: string }[] = [
  { key: 'expected', label: 'Expected' }, { key: 'present', label: 'Present' }, { key: 'absent', label: 'Absent' }, { key: 'late', label: 'Late' }, { key: 'unrostered', label: 'Unrostered' },
]

export default function LiveOperationsPage() {
  const { site } = useSite()
  const { can } = useTempoContext()
  const [params, setParams] = useSearchParams()
  const [live, setLive] = useState<Live | null>(null)
  const [conn, setConn] = useState<'connected' | 'reconnecting'>('connected')
  const [updated, setUpdated] = useState<Date | null>(null)
  const [openCase, setOpenCase] = useState<ExceptionItem | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const manage = can('labour.exception.manage')
  const tz = live?.site.timezone ?? site?.timezone ?? 'UTC'

  const load = useCallback(async (detect: boolean) => {
    if (!site) return
    try {
      // Detection is idempotent (dedup_key); run it here until the dedicated detector worker exists.
      if (detect && manage) await detectExceptions(site.site_id).catch(() => undefined)
      const l = await getLive(site.site_id)
      setLive(l); setUpdated(new Date()); setConn('connected')
    } catch { setConn('reconnecting') }
  }, [site, manage])

  useEffect(() => { setLive(null); void load(true); const t = setInterval(() => void load(true), 30000); return () => clearInterval(t) }, [load])
  useEffect(() => { const id = params.get('case'); if (id && live) { const c = live.exceptions.find((e) => e.id === id); if (c) setOpenCase(c) } }, [params, live])

  const win = useMemo(() => { const n = live ? new Date(live.as_of).getTime() : Date.now(); return { start: n - 4 * 3600e3, end: n + 8 * 3600e3, now: n } }, [live])
  const pct = (t: number) => Math.max(0, Math.min(100, ((t - win.start) / (win.end - win.start)) * 100))

  /** keepOpen: refresh the case in place (acknowledge/assign) instead of closing the panel (resolve/dismiss). */
  async function act(fn: () => Promise<unknown>, done: string, keepOpen = false) {
    setBusy(true); setMsg(null)
    try {
      const id = openCase?.id
      await fn(); setMsg(done); setReason('')
      if (keepOpen && site) { const l = await getLive(site.site_id); setLive(l); setUpdated(new Date()); setOpenCase(l.exceptions.find((e) => e.id === id) ?? null) }
      else { await load(false); setOpenCase(null) }
    } catch (e) { setMsg(e instanceof Error ? e.message : 'Action failed') } finally { setBusy(false) }
  }
  const openList = live?.exceptions.filter((e) => ['detected', 'triaged', 'assigned'].includes(e.state)) ?? []
  const closed = live?.exceptions.filter((e) => !['detected', 'triaged', 'assigned'].includes(e.state)) ?? []
  const rows = (live?.rows ?? []).filter((r) => r.state !== 'completed' || true)

  if (!site) return <Empty title="No site available" />
  return (
    <>
      <PageHead title="Live Operations" sub={<>{site.name} · {tz} · active shift view</>}>
        <span role="status" className="tp-row">
          {conn === 'connected' ? <Status tone="ok">Connected</Status> : <Status tone="bad">Reconnecting…</Status>}
          <span className="tp-muted tp-num">Last update {updated ? fmtTime(updated.toISOString(), tz, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }) : '—'}</span>
        </span>
        <button className="tp-btn" onClick={() => void load(true)}>Refresh</button>
      </PageHead>
      {live && <div style={{ marginBottom: 12 }}><SourcePills sources={live.data_sources} /></div>}
      {live && <FreshnessBanner sources={live.data_sources} attendanceVerified={live.attendance_verified} />}
      {live?.stale_message && <Banner tone="bad" title="Presence is unverified">{live.stale_message}</Banner>}
      {msg && <Banner tone="info" title={msg} />}

      <section className="tp-kpis" aria-label="Attendance counts">
        {COUNTS.map((c) => {
          const v = live?.counts[c.key]
          return (
            <div key={c.key} className="tp-card tp-kpi" title={live?.definitions[c.key]}>
              <div className="lbl">{c.label}</div>
              {!live ? <Skeleton h={28} w={60} /> : v == null ? <div className="val nodata">Not verified</div> : <div className="val">{v}</div>}
              <div className="meta">{live?.definitions[c.key] ?? ''}</div>
            </div>
          )
        })}
      </section>

      <div className="tp-grid">
        <section className="tp-card" aria-labelledby="h-tl">
          <header><h2 id="h-tl">Scheduled vs actual</h2><span className="tp-muted" style={{ fontSize: 12 }}>bar = scheduled shift · black tick = clock-in · red line = now</span></header>
          <div className="tp-body" style={{ maxHeight: 560, overflow: 'auto' }}>
            {!live ? <Skeleton h={240} /> : rows.length === 0 ? <Empty title="No shift is active in this window">Nothing rostered around now.</Empty> : (
              <table className="tp-table">
                <thead><tr><th>Worker</th><th>Status</th><th style={{ width: '46%' }}>Timeline ({fmtTime(new Date(win.start).toISOString(), tz)}–{fmtTime(new Date(win.end).toISOString(), tz)})</th></tr></thead>
                <tbody>
                  {rows.map((r: LiveRow) => {
                    const st = STATE[r.state] ?? { tone: 'neutral' as Tone, label: r.state }
                    return (
                      <tr key={`${r.worker_id}-${r.shift_id ?? r.attendance_session_id}`}>
                        <td><b>{r.worker_label}</b><div className="tp-muted" style={{ fontSize: 12 }}>{r.role ? `${r.role} · ${r.zone}` : 'no rostered shift'}</div></td>
                        <td><Status tone={st.tone}>{st.label}{r.minutes_late ? ` ${r.minutes_late}m` : ''}</Status></td>
                        <td>
                          <div className="tp-tl" role="img" aria-label={`${r.worker_label}: scheduled ${r.scheduled_start ? `${fmtTime(r.scheduled_start, tz)}–${fmtTime(r.scheduled_end, tz)}` : 'none'}, clocked in ${r.punch_in ? fmtTime(r.punch_in, tz) : 'not yet'}`}>
                            {r.scheduled_start && <div className="bar" style={{ left: `${pct(new Date(r.scheduled_start).getTime())}%`, width: `${pct(new Date(r.scheduled_end!).getTime()) - pct(new Date(r.scheduled_start).getTime())}%` }} />}
                            {r.punch_in && <div className="pin" title={`In ${fmtTime(r.punch_in, tz)}`} style={{ left: `${pct(new Date(r.punch_in).getTime())}%` }} />}
                            {r.punch_out && <div className="pin" title={`Out ${fmtTime(r.punch_out, tz)}`} style={{ left: `${pct(new Date(r.punch_out).getTime())}%`, background: 'var(--tp-ink-muted)' }} />}
                            <div className="now" style={{ left: `${pct(win.now)}%` }} />
                          </div>
                          <div className="tp-muted tp-num" style={{ fontSize: 11 }}>{r.scheduled_start ? `${fmtTime(r.scheduled_start, tz)}–${fmtTime(r.scheduled_end, tz)}` : ''} {r.punch_in ? `· in ${fmtTime(r.punch_in, tz)}` : ''}{r.punch_out ? ` · out ${fmtTime(r.punch_out, tz)}` : ''}</div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </section>

        <section className="tp-card" aria-labelledby="h-ex">
          <header><h2 id="h-ex">Exceptions</h2>{live && <Status tone={openList.length ? 'bad' : 'ok'}>{openList.length} open</Status>}</header>
          {!live ? <div className="tp-body"><Skeleton h={160} /></div> : live.exceptions.length === 0 ? <Empty title="No exceptions">Nothing detected for this site.</Empty> : (
            <ul className="tp-list" style={{ maxHeight: 620, overflow: 'auto' }}>
              {[...openList, ...closed].map((e) => (
                <li key={e.id}>
                  <button className="tp-item" onClick={() => setOpenCase(e)} style={{ opacity: closed.includes(e) ? 0.65 : 1 }}
                    aria-label={`${KIND_LABEL[e.kind] ?? e.kind}, ${e.severity}, ${STATE_LABEL[e.state]}, ${e.worker_label ?? 'site-level'}, age ${fmtAge(e.age_seconds)}`}>
                    <Status tone={closed.includes(e) ? 'neutral' : severityTone(e.severity)}>{closed.includes(e) ? STATE_LABEL[e.state] : e.severity}</Status>
                    <span><span className="t">{KIND_LABEL[e.kind] ?? e.kind}</span><br /><span className="s">{e.worker_label ?? 'Site-level'} · {fmtAge(e.age_seconds)} old · {STATE_LABEL[e.state]}</span></span>
                    <span aria-hidden="true">›</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {openCase && (
        <Drawer title={`${KIND_LABEL[openCase.kind] ?? openCase.kind}`} onClose={() => { setOpenCase(null); const p = new URLSearchParams(params); p.delete('case'); setParams(p, { replace: true }) }}>
          <dl className="tp-dl">
            <dt>Severity</dt><dd><Status tone={severityTone(openCase.severity)}>{openCase.severity}</Status></dd>
            <dt>State</dt><dd>{STATE_LABEL[openCase.state]}{openCase.owner_user_id ? ' · owned' : ' · unassigned'}</dd>
            <dt>Worker</dt><dd>{openCase.worker_label ?? '—'}</dd>
            <dt>Occurred at source</dt><dd>{fmtTime(openCase.source_occurred_at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}</dd>
            <dt>Detected by Tempo</dt><dd>{fmtTime(openCase.detected_at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })} · lag {fmtAge(openCase.detection_lag_seconds)}</dd>
            <dt>Age</dt><dd>{fmtAge(openCase.age_seconds)}</dd>
            <dt>Evidence</dt><dd><pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'var(--tp-font-mono)', fontSize: 12 }}>{JSON.stringify(openCase.evidence, null, 2)}</pre></dd>
            {openCase.resolution && (<><dt>Resolution</dt><dd>{openCase.resolution}</dd></>)}
          </dl>
          {['detected', 'triaged', 'assigned'].includes(openCase.state) && (manage ? (
            <div className="tp-stack" style={{ marginTop: 16 }}>
              <div className="tp-row">
                {openCase.state === 'detected' && <button className="tp-btn" disabled={busy} onClick={() => void act(() => acknowledgeException(openCase.id), 'Acknowledged', true)}>Acknowledge</button>}
                {openCase.state !== 'assigned' && <button className="tp-btn" disabled={busy} onClick={() => void act(() => assignException(openCase.id), 'Assigned to you', true)}>Assign to me</button>}
              </div>
              <label className="tp-field">Resolution note (required, min 3 characters)<textarea rows={3} value={reason} onChange={(e) => setReason(e.target.value)} /></label>
              <div className="tp-row">
                <button className="tp-btn primary" disabled={busy || reason.trim().length < 3} onClick={() => void act(() => resolveException(openCase.id, reason.trim()), 'Resolved')}>Resolve</button>
                <button className="tp-btn" disabled={busy || reason.trim().length < 3} onClick={() => void act(() => resolveException(openCase.id, reason.trim(), true), 'Dismissed')}>Dismiss</button>
              </div>
              <p className="tp-muted" style={{ fontSize: 12 }}>Corrections to a punch never overwrite the original event; they will create an approval-linked adjustment (not built yet).</p>
            </div>
          ) : <p className="tp-muted">You can view this exception but not change it.</p>)}
        </Drawer>
      )}
    </>
  )
}
