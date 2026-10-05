import { Link } from 'react-router-dom'
import { PageHead, Status } from '../components/ui'

const ARTICLES = [
  ['First roster readiness', 'Organisation, site, staff, workload and attendance choices before generating a draft.', '/data'],
  ['CSV import flow', 'Upload, map, validate, preview, confirm and download rejected rows without developer intervention.', '/data?tab=upload'],
  ['API ingestion', 'Scoped service credentials, idempotency keys, batch limits and row-level errors.', '/data?tab=api'],
  ['Roster states', 'Draft, submitted, approved, published and reconciled, including why edits invalidate approval.', '/roster'],
  ['Attendance corrections', 'Original punches, requested corrections, second approval and payable hours.', '/attendance'],
  ['Kiosk recovery', 'Device enrolment, online-only clocking, repeated taps, refresh and supervisor route during outages.', '/kiosk'],
]
const COLLECTIONS = [
  ['Launch a first roster', 'Data readiness, demand, planner, approval and publish checks.', '/roster'],
  ['Run daily operations', 'Live exceptions, attendance review, corrections and payroll readiness.', '/live'],
  ['Integrate data', 'CSV templates, API credentials, idempotency and row-error recovery.', '/data'],
]

export default function HelpPage() {
  return (
    <>
      <PageHead title="Help library" sub="Operational guidance linked to the working Tempo pages. The API reference remains discoverable for integration teams." />
      <section className="tp-command" aria-label="Help centre highlights">
        <div className="tp-command-main">
          <div><div className="tp-muted">Tempo help centre</div><h2>Find the operating path, then jump back into the working page.</h2></div>
          <div className="tp-command-grid">
            {COLLECTIONS.map(([title, body, href]) => (
              <Link key={title} to={href} className="tp-command-metric" style={{ textDecoration: 'none' }}>
                <div className="lbl">{title}</div>
                <div className="meta">{body}</div>
              </Link>
            ))}
          </div>
        </div>
        <aside className="tp-action-card">
          <h2>Documentation posture</h2>
          <div className="primary-line">Operational truth first</div>
          <p className="tp-muted" style={{ margin: 0 }}>Help should define source, freshness, authority and recovery steps. It should not promise unfinished connectors, payments or writeback.</p>
          <Status tone="neutral">Contextual help shell</Status>
        </aside>
      </section>
      <div className="tp-grid">
        <section className="tp-card">
          <header><h2>Customer tasks</h2><Status tone="neutral">Shell prepared</Status></header>
          <div className="tp-body">
            <div className="tp-tilegrid">
              {ARTICLES.map(([title, body, href]) => (
                <Link key={title} className="tp-tile" to={href}>
                  <b>{title}</b>
                  <span>{body}</span>
                </Link>
              ))}
            </div>
          </div>
        </section>
        <aside className="tp-stack">
          <section className="tp-card">
            <header><h2>API reference</h2><Status tone="risk">Environment dependent</Status></header>
            <div className="tp-body">
              <p className="tp-muted">Swagger/OpenAPI is served by the API in development and UAT. Use it with the same tenant permissions and service credentials described in Data.</p>
              <a className="tp-btn" href="/docs" target="_blank" rel="noreferrer">Open API docs</a>
            </div>
          </section>
          <section className="tp-card">
            <header><h2>Contextual help standard</h2></header>
            <div className="tp-body">
              <p className="tp-muted">Future pages should link here for metric definitions, setup prerequisites and recovery steps. Help must describe source, freshness and authority, not marketing promises.</p>
            </div>
          </section>
        </aside>
      </div>
    </>
  )
}
