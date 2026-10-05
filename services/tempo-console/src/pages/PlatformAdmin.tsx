import { Link } from 'react-router-dom'
import { PageHead, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'

const ROWS = [
  ['Tenant lifecycle', 'Create, suspend and review tenants through platform APIs.', 'Partial backend groundwork'],
  ['Plans and entitlements', 'Assign plan, site count, workforce band and negotiated terms.', 'API contract needed'],
  ['Integration health', 'Review connection freshness, failed rows, retries and reconnect instructions.', 'Customer pages partial'],
  ['Support access', 'Use time-boxed grants with reason, step-up and audit trail.', 'Use path still open'],
  ['Billing operations', 'Stripe signup and manual entitlement support.', 'Not integrated'],
]

export default function PlatformAdminPage() {
  const { access } = useTempoContext()
  return (
    <>
      <PageHead title="Platform administration" sub="Distinct operator surface for tenant management, support and commercial operations." />
      {!access?.platform_admin ? (
        <section className="tp-card"><div className="tp-body"><Status tone="bad">Platform administrator required</Status><p className="tp-muted">This route is visible only to platform operators in normal navigation. Direct links still rely on API permissions for any future data.</p></div></section>
      ) : (
        <>
          <section className="tp-command" aria-label="Platform operator cockpit">
            <div className="tp-command-main">
              <div className="tp-row" style={{ justifyContent: 'space-between' }}>
                <div><div className="tp-muted">Operator cockpit</div><h2>Platform controls are prepared, but tenant operations still need API contracts.</h2></div>
                <Status tone="risk">Controlled shell</Status>
              </div>
              <div className="tp-command-grid">
                <div className="tp-command-metric"><div className="lbl">Tenant lifecycle</div><div className="val">Partial</div><div className="meta">create/suspend APIs required</div></div>
                <div className="tp-command-metric"><div className="lbl">Support access</div><div className="val">Guarded</div><div className="meta">time-boxed grant flow open</div></div>
                <div className="tp-command-metric"><div className="lbl">Billing ops</div><div className="val">Pending</div><div className="meta">Stripe/manual entitlement records needed</div></div>
              </div>
            </div>
            <section className="tp-card">
              <header><h2>Support boundary</h2></header>
              <div className="tp-body">
                <p className="tp-muted">Entering a customer environment must show the tenant, reason, approver and expiry. It must never look like an ordinary customer login.</p>
                <Link className="tp-btn" to="/audit">Open global/customer audit</Link>
              </div>
            </section>
          </section>
          <div className="tp-grid">
            <section className="tp-card">
              <header><h2>Operator workspace</h2><Status tone="risk">Shell prepared</Status></header>
              <div className="tp-body">
                <table className="tp-table">
                  <thead><tr><th>Area</th><th>Purpose</th><th>Current state</th></tr></thead>
                  <tbody>{ROWS.map(([area, purpose, state]) => <tr key={area}><td><b>{area}</b></td><td>{purpose}</td><td><Status tone={state.includes('Not') || state.includes('needed') ? 'risk' : 'neutral'}>{state}</Status></td></tr>)}</tbody>
                </table>
              </div>
            </section>
            <aside className="tp-stack">
            <section className="tp-card">
              <header><h2>Next API contract</h2></header>
              <div className="tp-body">
                <p className="tp-muted">Add platform tenant list/detail, support-grant use, entitlement configuration, integration-health rollups and billing event records. Keep support diagnostics impersonation-free.</p>
              </div>
            </section>
              <section className="tp-card">
                <header><h2>Operational health</h2></header>
                <div className="tp-body tp-mini-bars">
                  {ROWS.map(([area, , state]) => <div key={area} className="tp-mini-bar"><span>{area}</span><span className="track"><span className="fill" style={{ display: 'block', width: state.includes('Partial') || state.includes('Customer') ? '45%' : state.includes('Not') || state.includes('needed') ? '20%' : '30%', background: state.includes('Not') || state.includes('needed') ? 'var(--tp-amber)' : 'var(--tp-chart-capacity)' }} /></span><span className="tp-muted">{state}</span></div>)}
                </div>
              </section>
            </aside>
          </div>
        </>
      )}
    </>
  )
}
