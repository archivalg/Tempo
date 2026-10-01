import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import type { DataSource, Kpi } from '../api/ops'
import { fmtAge } from '../lib/format'

export type Tone = 'ok' | 'risk' | 'bad' | 'neutral'
const ICON: Record<Tone, string> = { ok: '✓', risk: '▲', bad: '✕', neutral: '●' }

/** Status is always icon + text; colour is reinforcement only. */
export function Status({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`tp-badge ${tone}`} title={title}>
      <span aria-hidden="true">{ICON[tone]}</span>
      {children}
    </span>
  )
}

export const severityTone = (s: string): Tone => (s === 'critical' || s === 'high' ? 'bad' : s === 'medium' ? 'risk' : 'neutral')
export const KIND_LABEL: Record<string, string> = {
  late: 'Late', no_show: 'No-show', unrostered: 'Unrostered punch', missing_punch: 'Missing punch-out', early_departure: 'Early departure',
  overtime: 'Overtime', cert_expiry: 'Certification', connector_stale: 'Source stale',
}
export const STATE_LABEL: Record<string, string> = { detected: 'New', triaged: 'Acknowledged', assigned: 'Assigned', resolved: 'Resolved', dismissed: 'Dismissed' }

export function Skeleton({ h = 16, w = '100%' }: { h?: number; w?: number | string }) {
  return <div className="tp-skel" style={{ height: h, width: w }} aria-hidden="true" />
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="tp-empty" role="status">
      <b>{title}</b>
      {children}
    </div>
  )
}

export function Banner({ tone, title, children }: { tone: 'warn' | 'bad' | 'info'; title: string; children?: ReactNode }) {
  return (
    <div className={`tp-banner ${tone}`} role={tone === 'info' ? 'status' : 'alert'}>
      <span aria-hidden="true">{tone === 'info' ? 'i' : tone === 'warn' ? '▲' : '✕'}</span>
      <div>
        <strong>{title}</strong>
        {children}
      </div>
    </div>
  )
}

export function KpiCard({ k }: { k: Kpi }) {
  const [open, setOpen] = useState(false)
  const nodata = k.value == null
  const body = (
    <>
      <div className="lbl">
        {k.label}
        <button className="tp-info" aria-label={`Definition of ${k.label}`} aria-expanded={open} onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(!open) }}>i</button>
      </div>
      <div className={`val${nodata ? ' nodata' : ''}`}>{k.display}</div>
      <div className="meta">
        {nodata ? (k.reason ?? 'No verified source for this value') : k.denominator != null && k.key !== 'work_units' && k.key !== 'labour_cost' ? `${k.numerator ?? '—'} of ${k.denominator}` : k.basis}
      </div>
    </>
  )
  return (
    <div className="tp-card tp-kpi" style={{ position: 'relative' }}>
      <Link to={k.drill || '#'} style={{ color: 'inherit', textDecoration: 'none', display: 'flex', flexDirection: 'column', gap: 4 }} aria-label={`${k.label}: ${nodata ? 'no verified data' : k.display}. Open detail`}>
        {body}
      </Link>
      {open && (
        <div className="tp-pop" role="dialog" aria-label={`${k.label} definition`}>
          <dl style={{ margin: 0 }}>
            <dt>Definition</dt><dd>{k.definition}</dd>
            <dt>Basis</dt><dd>{k.basis}</dd>
            {k.numerator != null && k.denominator != null && (<><dt>Numerator / denominator</dt><dd className="tp-num">{k.numerator} / {k.denominator}</dd></>)}
            {k.reason && (<><dt>Note</dt><dd>{k.reason}</dd></>)}
          </dl>
        </div>
      )}
    </div>
  )
}

export function SourcePills({ sources }: { sources: DataSource[] }) {
  if (!sources.length) return <Status tone="risk">No sources registered</Status>
  return (
    <div className="tp-row" aria-label="Data sources">
      {sources.map((s) => {
        const tone: Tone = s.mode === 'live' && s.fresh ? 'ok' : s.mode === 'simulated' ? 'neutral' : 'bad'
        const word = s.mode === 'live' && s.fresh ? 'Live' : s.mode === 'simulated' ? 'Simulated' : s.mode === 'stale' ? 'Stale' : s.mode
        return (
          <Status key={s.key} tone={tone} title={s.note ?? undefined}>
            {s.label}: {word}
            {s.age_seconds != null && s.mode !== 'simulated' ? ` · ${fmtAge(s.age_seconds)} ago` : ''}
          </Status>
        )
      })}
    </div>
  )
}

/** Conspicuous whenever any input to the page is not verified live. */
export function FreshnessBanner({ sources, attendanceVerified }: { sources: DataSource[]; attendanceVerified?: boolean }) {
  const stale = sources.filter((s) => s.mode === 'stale' || s.mode === 'error' || (s.mode === 'live' && !s.fresh))
  const sim = sources.filter((s) => s.mode === 'simulated')
  if (!stale.length && !sim.length) return null
  return (
    <>
      {stale.length > 0 && (
        <Banner tone="warn" title="Some data is stale — figures that depend on it are not verified live">
          {stale.map((s) => (<div key={s.key}>{s.label}: last success {s.age_seconds != null ? `${fmtAge(s.age_seconds)} ago` : 'never'}. {s.note}</div>))}
          {attendanceVerified === false && <div>Presence counts are withheld rather than shown as "all present".</div>}
        </Banner>
      )}
      {sim.length > 0 && (
        <Banner tone="info" title="Synthetic / simulated data">
          {sim.map((s) => (<div key={s.key}>{s.label}. {s.note}</div>))}
        </Banner>
      )}
    </>
  )
}

export function Drawer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null
    ref.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => { document.removeEventListener('keydown', onKey); prev?.focus?.() }
  }, [onClose])
  return (
    <>
      <div className="tp-scrim" onClick={onClose} />
      <aside className="tp-drawer" role="dialog" aria-modal="true" aria-label={title} ref={ref} tabIndex={-1}>
        <header>
          <h2 style={{ margin: 0, fontSize: 16 }}>{title}</h2>
          <button className="tp-btn" onClick={onClose} aria-label="Close panel">Close</button>
        </header>
        <div>{children}</div>
      </aside>
    </>
  )
}

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="tp-page-head">
      <div>
        <h1>{title}</h1>
        {sub && <div className="tp-sub">{sub}</div>}
      </div>
      <div className="tp-spacer" />
      {children}
    </div>
  )
}

export const ROSTER_STEPS = ['draft', 'pending_approval', 'approved', 'published'] as const
const STEP_LABEL: Record<string, string> = { draft: 'Draft', pending_approval: 'Submitted', approved: 'Approved', published: 'Published' }

/** draft → submitted → approved → published progress, with terminal states called out. */
export function RosterSteps({ state }: { state: string }) {
  const norm = state === 'reconciled' ? 'published' : state
  const idx = ROSTER_STEPS.indexOf(norm as (typeof ROSTER_STEPS)[number])
  if (idx < 0) return <Status tone={state === 'rejected' ? 'bad' : 'neutral'}>{state.replace('_', ' ')}</Status>
  return (
    <div className="tp-steps" role="list" aria-label="Roster progress">
      {ROSTER_STEPS.map((s, i) => (
        <span key={s} role="listitem" className={`tp-step${i < idx || (i === idx && (norm === 'published')) ? ' done' : i === idx ? ' now' : ''}`} aria-current={i === idx ? 'step' : undefined}>
          {i < idx || (i === idx && norm === 'published') ? '✓ ' : ''}{STEP_LABEL[s]}{state === 'reconciled' && s === 'published' ? ' · reconciled' : ''}
        </span>
      ))}
    </div>
  )
}

/** Download the on-screen report as CSV. Hidden for callers without labour.export; errors are shown, never swallowed. */
export function ExportButton({ run, label = 'Export CSV' }: { run: () => Promise<void>; label?: string }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  return (
    <span className="tp-row">
      <button className="tp-btn" disabled={busy} onClick={() => { setBusy(true); setErr(null); run().catch((e) => setErr(e.message)).finally(() => setBusy(false)) }}>{busy ? 'Preparing…' : `⭳ ${label}`}</button>
      {err && <span role="status" className="tp-badge bad">✕ {err}</span>}
    </span>
  )
}
