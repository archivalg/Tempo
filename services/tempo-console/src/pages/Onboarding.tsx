import { useState, type FormEvent } from 'react'
import { Banner, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { enrollCredential } from '../api/attendance'
import type { CredentialEnrollResponse } from '../api/types'
import { createConnection, createTenantScope, listConnections, listConnectors, listTenantScopes } from '../api/onboarding'

export function OnboardingPage() {
  const { context, can } = useTempoContext()
  const catalogue = useApi(() => (context ? listConnectors(context) : Promise.resolve([])), [context])
  const scopes = useApi(() => (context ? listTenantScopes(context) : Promise.resolve([])), [context])
  const connections = useApi(() => (context ? listConnections(context) : Promise.resolve({ connections: [] })), [context])

  const [scopeSiteId, setScopeSiteId] = useState('')
  const [scopeCompanyId, setScopeCompanyId] = useState('')
  const [scopeError, setScopeError] = useState<unknown>(null)
  const [connSourceSystem, setConnSourceSystem] = useState('deputy')
  const [connSiteId, setConnSiteId] = useState('')
  const [connDisplayName, setConnDisplayName] = useState('')
  const [connError, setConnError] = useState<unknown>(null)
  const [credWorkerId, setCredWorkerId] = useState('')
  const [credPin, setCredPin] = useState('')
  const [credNfcTagId, setCredNfcTagId] = useState('')
  const [credResult, setCredResult] = useState<CredentialEnrollResponse | null>(null)
  const [credError, setCredError] = useState<unknown>(null)

  async function handleCreateScope(event: FormEvent) {
    event.preventDefault()
    if (!context) return
    setScopeError(null)
    try {
      await createTenantScope(context, { site_id: scopeSiteId, company_id: scopeCompanyId || undefined })
      setScopeSiteId('')
      setScopeCompanyId('')
      scopes.reload()
    } catch (err) { setScopeError(err) }
  }

  async function handleEnrollCredential(event: FormEvent) {
    event.preventDefault()
    if (!context) return
    setCredError(null)
    setCredResult(null)
    try {
      const result = await enrollCredential(context, credWorkerId, { pin: credPin || undefined, nfcTagId: credNfcTagId || undefined })
      setCredResult(result)
      setCredPin('')
      setCredNfcTagId('')
    } catch (err) { setCredError(err) }
  }

  async function handleCreateConnection(event: FormEvent) {
    event.preventDefault()
    if (!context) return
    setConnError(null)
    try {
      await createConnection(context, { source_system: connSourceSystem, site_id: connSiteId, display_name: connDisplayName || undefined })
      setConnSiteId('')
      setConnDisplayName('')
      connections.reload()
    } catch (err) { setConnError(err) }
  }

  const errText = (e: unknown) => (e instanceof Error ? e.message : String(e))
  const connectionRows = connections.data?.connections ?? []
  const verifiedConnections = connectionRows.filter((c) => c.status === 'verified').length
  const pendingConnections = connectionRows.filter((c) => c.status !== 'verified').length
  const setupSteps = [
    { title: 'Register scope', done: (scopes.data?.length ?? 0) > 0, detail: scopes.data?.length ? `${scopes.data.length} scope${scopes.data.length === 1 ? '' : 's'} registered` : 'Link a Tempo site to an external company/site scope.' },
    { title: 'Choose connection', done: connectionRows.length > 0, detail: connectionRows.length ? `${connectionRows.length} connection${connectionRows.length === 1 ? '' : 's'} registered` : 'Register Deputy first; second vendor remains open.' },
    { title: 'Verify credentials', done: verifiedConnections > 0, detail: verifiedConnections ? `${verifiedConnections} verified` : `${pendingConnections} pending credential or mapping verification` },
    { title: 'Enrol clock access', done: !!credResult, detail: credResult ? `Last enrolment: worker ${credResult.worker_id}` : 'Create kiosk PIN/NFC credentials for native T&A.' },
  ]
  const nextStep = setupSteps.find((s) => !s.done)
  return (
    <>
      <PageHead title="Connections & onboarding" sub="Register scopes, prepare workforce connections and enrol kiosk credentials. Live vendor credentials are not configured from this page yet." />
      <Banner tone="info" title="Current release boundary">Deputy is the first confirmed external workforce connection. The second vendor remains open. Registered connections stay pending until credentials, mapping and verified sync are implemented.</Banner>

      <section className="tp-command" aria-label="Onboarding progress">
        <div className="tp-action-card">
          <div className="tp-row" style={{ justifyContent: 'space-between' }}>
            <h2>Setup journey</h2>
            <Status tone={nextStep ? 'risk' : 'ok'}>{setupSteps.filter((s) => s.done).length} of {setupSteps.length} done</Status>
          </div>
          <div className="tp-workflow">
            {setupSteps.map((s, i) => (
              <div key={s.title} className={`tp-workflow-step${s.done ? ' done' : s === nextStep ? ' now' : ''}`}>
                <div className="num">Step {i + 1}</div>
                <b>{s.title}</b>
                <p className="tp-muted" style={{ margin: '6px 0 0', fontSize: 12.5 }}>{s.detail}</p>
              </div>
            ))}
          </div>
        </div>
        <aside className="tp-action-card">
          <h2>Next setup action</h2>
          <div className="primary-line">{nextStep?.title ?? 'Ready for verified sync'}</div>
          <p className="tp-muted" style={{ margin: 0 }}>{nextStep?.detail ?? 'All visible onboarding steps are complete. Keep connection health monitored before advertising live vendor support.'}</p>
          <div className="tp-row">
            <Status tone={verifiedConnections ? 'ok' : 'risk'}>{verifiedConnections} verified connection{verifiedConnections === 1 ? '' : 's'}</Status>
            <Status tone={pendingConnections ? 'risk' : 'neutral'}>{pendingConnections} pending</Status>
          </div>
        </aside>
      </section>

      <div className="tp-grid">
        <div className="tp-stack">
          <section className="tp-card">
            <header><h2>Connection catalogue</h2><Status tone="risk">Credentials pending</Status></header>
            {catalogue.error ? <div className="tp-body"><Banner tone="bad" title="Could not load catalogue">{errText(catalogue.error)}</Banner></div> : null}
            {!catalogue.data ? <div className="tp-body"><Skeleton h={120} /></div> : catalogue.data.length === 0 ? <Empty title="No connectors registered" /> : (
              <table className="tp-table"><thead><tr><th>Source</th><th>Covers</th><th>Status</th><th>Notes</th></tr></thead><tbody>
                {catalogue.data.map((c) => (
                  <tr key={c.source_system}><td><b>{c.display_name}</b><div className="tp-muted" style={{ fontSize: 12 }}>{c.source_system}</div></td><td>{c.entity_types.join(', ')}</td><td><Status tone={c.status === 'available' ? 'neutral' : 'risk'}>{c.status.replace(/_/g, ' ')}</Status></td><td>{c.notes}</td></tr>
                ))}
              </tbody></table>
            )}
          </section>

          <section className="tp-card">
            <header><h2>Registered connections</h2></header>
            {connError ? <div className="tp-body"><Banner tone="bad" title="Could not register connection">{errText(connError)}</Banner></div> : null}
            <form className="tp-body tp-row" onSubmit={handleCreateConnection}>
              <label className="tp-field">Source system
                <select value={connSourceSystem} onChange={(e) => setConnSourceSystem(e.target.value)}>
                  {(catalogue.data ?? []).map((c) => <option key={c.source_system} value={c.source_system}>{c.display_name}</option>)}
                </select>
              </label>
              <label className="tp-field">Site ID<input value={connSiteId} onChange={(e) => setConnSiteId(e.target.value)} required /></label>
              <label className="tp-field">Display name<input value={connDisplayName} onChange={(e) => setConnDisplayName(e.target.value)} placeholder="e.g. Deputy Melbourne" /></label>
              <button className="tp-btn primary" type="submit" disabled={!can('labour.configure') || !connSiteId}>Register connection</button>
            </form>
            {!connections.data ? <div className="tp-body"><Skeleton h={90} /></div> : connectionRows.length === 0 ? <Empty title="No connections registered yet" /> : (
              <table className="tp-table"><thead><tr><th>Connection</th><th>Source</th><th>Site</th><th>Status</th></tr></thead><tbody>
                {connectionRows.map((c) => <tr key={c.connection_id}><td>{c.connection_id}</td><td>{c.source_system}</td><td>{c.site_id}</td><td><Status tone={c.status === 'verified' ? 'ok' : c.status === 'failed' ? 'bad' : 'risk'}>{c.status.replace(/_/g, ' ')}</Status></td></tr>)}
              </tbody></table>
            )}
          </section>
        </div>

        <aside className="tp-stack">
          <section className="tp-card">
            <header><h2>Tenant scopes</h2></header>
            <form className="tp-body tp-stack" onSubmit={handleCreateScope}>
              <label className="tp-field">Site ID<input value={scopeSiteId} onChange={(e) => setScopeSiteId(e.target.value)} required /></label>
              <label className="tp-field">Company ID (optional)<input value={scopeCompanyId} onChange={(e) => setScopeCompanyId(e.target.value)} /></label>
              {scopeError ? <Banner tone="bad" title="Could not register scope">{errText(scopeError)}</Banner> : null}
              <button className="tp-btn primary" type="submit" disabled={!can('labour.configure') || !scopeSiteId}>Register scope</button>
            </form>
            {!scopes.data ? <div className="tp-body"><Skeleton h={60} /></div> : scopes.data.length === 0 ? <Empty title="No scopes registered" /> : (
              <ul className="tp-list">{scopes.data.map((s) => <li key={s.site_id} className="tp-item" style={{ gridTemplateColumns: '1fr auto', cursor: 'default' }}><span><b>{s.site_id}</b><br /><span className="s">{s.company_id ?? 'No company scope'}</span></span><Status tone="neutral">Registered</Status></li>)}</ul>
            )}
          </section>

          <section className="tp-card">
            <header><h2>Clock-in credentials</h2></header>
            <form className="tp-body tp-stack" onSubmit={handleEnrollCredential}>
              <p className="tp-muted" style={{ margin: 0 }}>Enrols a worker PIN and/or NFC tag for the browser kiosk. The page confirms only what it just wrote; credential history still needs an API.</p>
              <label className="tp-field">Worker ID<input value={credWorkerId} onChange={(e) => setCredWorkerId(e.target.value)} required /></label>
              <label className="tp-field">PIN<input value={credPin} onChange={(e) => setCredPin(e.target.value)} inputMode="numeric" /></label>
              <label className="tp-field">NFC tag ID<input value={credNfcTagId} onChange={(e) => setCredNfcTagId(e.target.value)} /></label>
              {credError ? <Banner tone="bad" title="Could not enrol credential">{errText(credError)}</Banner> : null}
              <button className="tp-btn primary" type="submit" disabled={!can('labour.configure') || !credWorkerId || (!credPin && !credNfcTagId)}>Enrol credential</button>
              {credResult && <Status tone="ok">Worker {credResult.worker_id}: {credResult.has_pin ? 'PIN enrolled' : 'no PIN'}, {credResult.has_nfc ? 'NFC enrolled' : 'no NFC'}</Status>}
            </form>
          </section>
        </aside>
      </div>
    </>
  )
}
