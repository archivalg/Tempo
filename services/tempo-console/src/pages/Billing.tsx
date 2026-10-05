import type { CSSProperties } from 'react'
import { PageHead, Status } from '../components/ui'

const TIERS = [
  ['Essentials', 'A$1,500 / site / month', 'Focused planning and native attendance foundation.'],
  ['Optimise', 'A$3,500 / site / month', 'Adds optimisation workflows and richer reporting.'],
  ['Orchestrate', 'A$6,500 / site / month', 'For multi-site orchestration and advanced controls.'],
  ['Network', 'Custom', 'Negotiated network and enterprise arrangements.'],
]

export default function BillingPage() {
  const allowance = 250
  const measured = 0
  const pct = Math.min(100, Math.round((measured / allowance) * 100))
  return (
    <>
      <PageHead title="Plans & billing" sub="Commercial model shell: site-based plans, workforce allowances and unlimited platform users. Prices are indicative until approved." />
      <section className="tp-command" aria-label="Commercial readiness">
        <div className="tp-action-card">
          <div className="tp-score">
            <div className="tp-score-ring" style={{ '--score': 35 } as CSSProperties}><span>35%</span></div>
            <div>
              <h2>Commercial readiness</h2>
              <p className="tp-muted" style={{ margin: '4px 0 10px' }}>Plan language and allowance bands are visible, but entitlement APIs, measured active-worker counts and Stripe reconciliation are not accepted yet.</p>
              <div className="tp-meter risk"><span style={{ width: '35%' }} /></div>
            </div>
          </div>
        </div>
        <aside className="tp-action-card">
          <h2>Current subscription state</h2>
          <div className="primary-line">Not configured</div>
          <p className="tp-muted" style={{ margin: 0 }}>No live Stripe product, subscription, invoice or entitlement record is shown on this page.</p>
          <div className="tp-row"><Status tone="risk">Stripe pending</Status><Status tone="neutral">Manual entitlement pending</Status></div>
        </aside>
      </section>
      <section className="tp-card" style={{ marginBottom: 16 }}>
        <header><h2>Plan model</h2><Status tone="risk">Configuration pending</Status></header>
        <div className="tp-body">
          <div className="tp-tilegrid">
            {TIERS.map(([name, price, note]) => (
              <div className="tp-tile" key={name}>
                <b>{name}</b>
                <span className="tp-num">{price}</span>
                <small>{note}</small>
              </div>
            ))}
          </div>
        </div>
      </section>
      <div className="tp-cols2">
        <section className="tp-card">
          <header><h2>Workforce allowance</h2></header>
          <div className="tp-body tp-stack">
            <div>
              <div className="tp-row" style={{ justifyContent: 'space-between' }}><b>Measured active workers</b><span className="tp-muted">No verified billing measurement</span></div>
              <div className="tp-meter" aria-label={`${measured} of ${allowance} active-worker allowance`}><span style={{ width: `${pct}%` }} /></div>
            </div>
            <table className="tp-table">
              <thead><tr><th>Band</th><th>Status</th></tr></thead>
              <tbody>
                {['Up to 250 active workers', '251-500 active workers', '501-1,000 active workers', '1,000+ active workers'].map((band) => <tr key={band}><td>{band}</td><td><Status tone="neutral">Defined, not billed</Status></td></tr>)}
              </tbody>
            </table>
          </div>
        </section>
        <section className="tp-card">
          <header><h2>Payment readiness</h2><Status tone="neutral">No live Stripe products</Status></header>
          <div className="tp-body tp-stack">
            <p className="tp-muted">Tempo must support self-service Stripe signup and platform-created tenants without Stripe, but this UI pass does not create products, charge customers or claim payment integration is complete.</p>
            <p className="tp-muted">Next implementation step: add plan/version APIs, entitlement checks, measured active-worker counts and manual entitlement records before enabling payment capture.</p>
          </div>
        </section>
      </div>
    </>
  )
}
