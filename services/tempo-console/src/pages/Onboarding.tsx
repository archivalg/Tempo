import { useState, type FormEvent } from 'react'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import {
  createConnection,
  createTenantScope,
  listConnections,
  listConnectors,
  listTenantScopes,
} from '../api/onboarding'

export function OnboardingPage() {
  const { context } = useTempoContext()
  const catalogue = useApi(() => listConnectors(context!), [context])
  const scopes = useApi(() => listTenantScopes(context!), [context])
  const connections = useApi(() => listConnections(context!), [context])

  const [scopeSiteId, setScopeSiteId] = useState('')
  const [scopeCompanyId, setScopeCompanyId] = useState('')
  const [scopeError, setScopeError] = useState<unknown>(null)

  const [connSourceSystem, setConnSourceSystem] = useState('deputy')
  const [connSiteId, setConnSiteId] = useState('')
  const [connDisplayName, setConnDisplayName] = useState('')
  const [connError, setConnError] = useState<unknown>(null)

  async function handleCreateScope(event: FormEvent) {
    event.preventDefault()
    setScopeError(null)
    try {
      await createTenantScope(context!, { site_id: scopeSiteId, company_id: scopeCompanyId || undefined })
      setScopeSiteId('')
      setScopeCompanyId('')
      scopes.reload()
    } catch (err) {
      setScopeError(err)
    }
  }

  async function handleCreateConnection(event: FormEvent) {
    event.preventDefault()
    setConnError(null)
    try {
      await createConnection(context!, {
        source_system: connSourceSystem,
        site_id: connSiteId,
        display_name: connDisplayName || undefined,
      })
      setConnSiteId('')
      setConnDisplayName('')
      connections.reload()
    } catch (err) {
      setConnError(err)
    }
  }

  return (
    <div className="page">
      <h1>Onboarding</h1>
      <p className="hint">
        Requires <code>labour.configure</code> (Tenant Admin). Registering a connection never configures a live
        vendor credential or triggers ingestion — see services/tempo-api README's Phase F section; it stays{' '}
        <code>pending_credentials</code> until an engineer wires up a real client.
      </p>

      <section className="card">
        <h2>Connector catalogue</h2>
        <ErrorBanner error={catalogue.error} />
        {catalogue.data && (
          <table>
            <thead>
              <tr>
                <th>Source system</th>
                <th>Display name</th>
                <th>Entity types</th>
                <th>Status</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {catalogue.data.map((c) => (
                <tr key={c.source_system}>
                  <td>{c.source_system}</td>
                  <td>{c.display_name}</td>
                  <td>{c.entity_types.join(', ')}</td>
                  <td>{c.status}</td>
                  <td>{c.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>Tenant scopes</h2>
        <form onSubmit={handleCreateScope}>
          <label>
            Site ID
            <input value={scopeSiteId} onChange={(e) => setScopeSiteId(e.target.value)} required />
          </label>
          <label>
            Company ID (optional)
            <input value={scopeCompanyId} onChange={(e) => setScopeCompanyId(e.target.value)} />
          </label>
          <ErrorBanner error={scopeError} />
          <button type="submit">Register scope</button>
        </form>
        <ErrorBanner error={scopes.error} />
        {scopes.data && (
          <ul>
            {scopes.data.map((s) => (
              <li key={s.site_id}>
                {s.site_id} {s.company_id ? `(${s.company_id})` : ''}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="card">
        <h2>Connections</h2>
        <form onSubmit={handleCreateConnection}>
          <label>
            Source system
            <select value={connSourceSystem} onChange={(e) => setConnSourceSystem(e.target.value)}>
              {(catalogue.data ?? []).map((c) => (
                <option key={c.source_system} value={c.source_system}>
                  {c.display_name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Site ID (must already have a registered tenant scope)
            <input value={connSiteId} onChange={(e) => setConnSiteId(e.target.value)} required />
          </label>
          <label>
            Display name (optional)
            <input value={connDisplayName} onChange={(e) => setConnDisplayName(e.target.value)} />
          </label>
          <ErrorBanner error={connError} />
          <button type="submit">Register connection</button>
        </form>
        <ErrorBanner error={connections.error} />
        {connections.data && (
          <table>
            <thead>
              <tr>
                <th>Connection ID</th>
                <th>Source system</th>
                <th>Site</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {connections.data.connections.map((c) => (
                <tr key={c.connection_id}>
                  <td>{c.connection_id}</td>
                  <td>{c.source_system}</td>
                  <td>{c.site_id}</td>
                  <td>
                    <StatusBadge status={c.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
