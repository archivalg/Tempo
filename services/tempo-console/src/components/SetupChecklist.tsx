import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getChecklist, type Checklist } from '../api/imports'
import { Status } from './ui'

/** Guided setup: what is done, what is missing in plain words, and one clear next step. */
export function SetupChecklist({ compact = false }: { compact?: boolean }) {
  const [c, setC] = useState<Checklist | null>(null)
  useEffect(() => { getChecklist().then(setC).catch(() => undefined) }, [])
  if (!c || (compact && c.complete)) return null
  const next = c.steps.find((s) => s.key === c.next)
  if (compact) {
    return (
      <section className="tp-card" style={{ marginBottom: 12 }} aria-label="Finish setting up">
        <div className="tp-body tp-row" style={{ justifyContent: 'space-between' }}>
          <span><strong>Finish setting up — {c.done} of {c.total} steps done.</strong> <span className="tp-muted">Next: {next?.title}. {next?.detail}</span></span>
          <Link className="tp-btn primary" style={{ textDecoration: 'none' }} to={next?.link ?? '/data'}>{next?.link ? 'Do it now' : 'See the checklist'}</Link>
        </div>
      </section>
    )
  }
  return (
    <section className="tp-card" aria-label="Setup checklist"><header><h2>Getting started</h2><span className="tp-muted">{c.done} of {c.total} done</span></header>
      <ol className="tp-list" style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {c.steps.map((s) => (
          <li key={s.key} className="tp-item" style={{ gridTemplateColumns: 'auto 1fr auto', cursor: 'default' }}>
            <Status tone={s.state === 'done' ? 'ok' : s.key === c.next ? 'risk' : 'neutral'}>{s.state === 'done' ? 'Done' : s.key === c.next ? 'Next' : 'To do'}</Status>
            <span><span className="t">{s.title}</span><br /><span className="s">{s.detail}</span></span>
            {s.state === 'todo' && s.link ? <Link className="tp-btn" style={{ textDecoration: 'none' }} to={s.link}>Open</Link> : <span />}
          </li>))}
      </ol>
    </section>
  )
}
