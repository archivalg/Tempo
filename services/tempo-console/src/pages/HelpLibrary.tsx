import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ARTICLES, HELP_VERSION, SECTIONS, type Article, type Availability } from '../help/articles'
import { BASE_URL } from '../api/client'
import { PageHead, Status } from '../components/ui'

const TONE: Record<Availability, 'ok' | 'neutral' | 'risk' | 'bad'> = { available: 'ok', 'read-only': 'neutral', planned: 'risk', unsupported: 'bad' }
const LABEL: Record<Availability, string> = { available: 'Available', 'read-only': 'Read-only', planned: 'Planned — not available', unsupported: 'Not supported' }

function ApiDocs() {
  const origin = BASE_URL.replace(/\/v1$/, '')
  return (
    <section className="tp-card"><header><h2>API documentation</h2></header><div className="tp-body tp-stack">
      <p style={{ margin: 0 }}>The data API loads master data, forecasts and workload from your own systems using a service credential. Only the supported ingestion endpoints are described here; internal routes are not published.</p>
      <div className="tp-row"><a className="tp-btn primary" style={{ textDecoration: 'none' }} href={`${BASE_URL}/api/docs`} target="_blank" rel="noreferrer">Open the interactive reference</a>
        <a className="tp-btn" style={{ textDecoration: 'none' }} href={`${BASE_URL}/api/openapi.json`} download="tempo-data-api-openapi.json">Download the OpenAPI schema</a></div>
      <pre style={{ overflow: 'auto', background: 'var(--tp-surface-2)', padding: 10, borderRadius: 6, fontSize: 12.5 }}>{`curl -X POST ${origin}/v1/imports/batches \\
  -H "Authorization: Bearer tsc_…" -H "Idempotency-Key: feed-2026-10-05" -H "Content-Type: application/json" \\
  -d '{"data_class":"bulk","apply":true,"rows":[{"site":"mel_dc_01","activity":"picking","period_start":"2026-10-05","grain":"day","units":26140}]}'`}</pre>
      <p className="tp-muted" style={{ margin: 0 }}>Create a credential in Data → API credentials. The secret is shown once.</p>
    </div></section>
  )
}

function ArticleView({ a }: { a: Article }) {
  return (
    <article className="tp-card" aria-label={a.title}><header><h2>{a.title}</h2><Status tone={TONE[a.status]}>{LABEL[a.status]}</Status></header>
      <div className="tp-body tp-stack">
        {a.body.map((p, i) => <p key={i} style={{ margin: 0 }}>{p}</p>)}
        {a.steps && <ol style={{ margin: 0, paddingLeft: 20 }}>{a.steps.map((s, i) => <li key={i}>{s}</li>)}</ol>}
        {a.link && <Link className="tp-btn" style={{ textDecoration: 'none', width: 'fit-content' }} to={a.link.to}>{a.link.label}</Link>}
        {a.id === 'api' && <ApiDocs />}
      </div>
    </article>
  )
}

/** Searchable, versioned help. Content lives in src/help/articles.ts and says what is available, read-only, planned or unsupported. */
export default function HelpLibrary() {
  const { id } = useParams()
  const [q, setQ] = useState('')
  const hits = useMemo(() => {
    const t = q.trim().toLowerCase()
    if (!t) return ARTICLES
    return ARTICLES.filter((a) => `${a.title} ${a.summary} ${a.body.join(' ')} ${(a.steps ?? []).join(' ')}`.toLowerCase().includes(t))
  }, [q])
  const one = id ? ARTICLES.find((a) => a.id === id || (id === 'api' && a.id === 'api')) : undefined
  return (
    <>
      <PageHead title="Help library" sub={`Task-based guidance for what Tempo does today · version ${HELP_VERSION}`} />
      <div className="tp-row" style={{ marginBottom: 12 }}><input type="search" aria-label="Search help" placeholder="Search help (for example “payroll”, “PIN”, “import”)" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 320 }} />{id && <Link className="tp-btn" style={{ textDecoration: 'none' }} to="/help">All help</Link>}</div>
      {one && !q ? <ArticleView a={one} /> : (
        <div className="tp-stack">
          {q && <p className="tp-muted" role="status">{hits.length} result{hits.length === 1 ? '' : 's'}</p>}
          {SECTIONS.map((s) => { const list = hits.filter((a) => a.section === s); if (list.length === 0) return null; return (
            <section key={s} className="tp-card" aria-label={s}><header><h2>{s}</h2></header>
              <ul className="tp-list" style={{ listStyle: 'none', padding: 0, margin: 0 }}>{list.map((a) => (
                <li key={a.id} className="tp-item" style={{ gridTemplateColumns: '1fr auto' }}><span><Link className="t" to={`/help/${a.id}`}>{a.title}</Link><br /><span className="s">{a.summary}</span></span><Status tone={TONE[a.status]}>{LABEL[a.status]}</Status></li>))}</ul></section>) })}
          {hits.length === 0 && <p>Nothing matches. Try fewer words, or contact your Ensemble Solutions representative.</p>}
        </div>)}
    </>
  )
}
