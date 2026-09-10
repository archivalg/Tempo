import { useState, type FormEvent } from 'react'
import { ErrorBanner } from '../components/ErrorBanner'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { addCertification, createProvider, listProviders, listSuppliedWorkers, registerSuppliedWorker } from '../api/providers'

export function LabourProvidersPage() {
  const { context } = useTempoContext()
  const providers = useApi(() => listProviders(context!), [context])

  const [providerName, setProviderName] = useState('')
  const [providerError, setProviderError] = useState<unknown>(null)

  const [activeProviderId, setActiveProviderId] = useState(context?.provider_id ?? '')
  const workers = useApi(
    () => (activeProviderId ? listSuppliedWorkers(context!, activeProviderId) : Promise.resolve([])),
    [context, activeProviderId],
  )

  const [workerSite, setWorkerSite] = useState(context?.site_ids[0] ?? '')
  const [workerError, setWorkerError] = useState<unknown>(null)

  const [certWorkerId, setCertWorkerId] = useState('')
  const [certSkillCode, setCertSkillCode] = useState('')
  const [certValidFrom, setCertValidFrom] = useState('')
  const [certError, setCertError] = useState<unknown>(null)

  async function handleCreateProvider(event: FormEvent) {
    event.preventDefault()
    setProviderError(null)
    try {
      await createProvider(context!, providerName)
      setProviderName('')
      providers.reload()
    } catch (err) {
      setProviderError(err)
    }
  }

  async function handleRegisterWorker(event: FormEvent) {
    event.preventDefault()
    setWorkerError(null)
    try {
      await registerSuppliedWorker(context!, activeProviderId, { home_site: workerSite })
      workers.reload()
    } catch (err) {
      setWorkerError(err)
    }
  }

  async function handleAddCertification(event: FormEvent) {
    event.preventDefault()
    setCertError(null)
    try {
      await addCertification(context!, activeProviderId, certWorkerId, {
        skill_code: certSkillCode,
        valid_from: new Date(certValidFrom).toISOString(),
      })
      setCertSkillCode('')
      setCertValidFrom('')
      workers.reload()
    } catch (err) {
      setCertError(err)
    }
  }

  return (
    <div className="page">
      <h1>Labour providers</h1>
      <p className="hint">
        Business Spec §8's Labour Provider role: "manage supplied workers, certifications, shift assignments."
        Registering a provider requires <code>labour.configure</code> (Tenant Admin); managing a provider's own
        supplied workers requires <code>labour.provider.manage</code> with a matching provider ID — a role and
        permission this pass added, since the Integration Spec's §5.2 table has no row for this role. A provider
        can only view which shifts their workers have been assigned, never create or edit one directly — Tempo's
        own roster optimiser stays the single source of truth for scheduling.
      </p>

      <section className="card">
        <h2>Providers</h2>
        <form onSubmit={handleCreateProvider}>
          <label>
            Name
            <input value={providerName} onChange={(e) => setProviderName(e.target.value)} required />
          </label>
          <ErrorBanner error={providerError} />
          <button type="submit">Register provider</button>
        </form>
        <ErrorBanner error={providers.error} />
        {providers.data && providers.data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Provider ID</th>
                <th>Name</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {providers.data.map((p) => (
                <tr key={p.provider_id}>
                  <td>{p.provider_id}</td>
                  <td>{p.name}</td>
                  <td>{p.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="card">
        <h2>Supplied workers</h2>
        <div className="filters">
          <label>
            Provider ID
            <input value={activeProviderId} onChange={(e) => setActiveProviderId(e.target.value)} />
          </label>
          <button onClick={workers.reload} disabled={!activeProviderId}>
            Refresh
          </button>
        </div>
        <ErrorBanner error={workers.error} />
        {workers.data && workers.data.length === 0 && <p>No supplied workers registered for this provider yet.</p>}
        {workers.data && workers.data.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Worker ID</th>
                <th>Home site</th>
                <th>Certifications</th>
                <th>Upcoming shifts</th>
              </tr>
            </thead>
            <tbody>
              {workers.data.map((w) => (
                <tr key={w.worker_id}>
                  <td>{w.worker_id}</td>
                  <td>{w.home_site}</td>
                  <td>{w.certifications.length === 0 ? '—' : w.certifications.map((c) => c.skill_code).join(', ')}</td>
                  <td>{w.upcoming_shifts.length === 0 ? '—' : `${w.upcoming_shifts.length} shift(s)`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <h3>Register a supplied worker</h3>
        <form onSubmit={handleRegisterWorker}>
          <label>
            Home site
            <input value={workerSite} onChange={(e) => setWorkerSite(e.target.value)} required />
          </label>
          <ErrorBanner error={workerError} />
          <button type="submit" disabled={!activeProviderId}>
            Register worker
          </button>
        </form>

        <h3>Add a certification</h3>
        <form onSubmit={handleAddCertification}>
          <label>
            Worker ID
            <input value={certWorkerId} onChange={(e) => setCertWorkerId(e.target.value)} required />
          </label>
          <label>
            Skill code
            <input value={certSkillCode} onChange={(e) => setCertSkillCode(e.target.value)} required />
          </label>
          <label>
            Valid from
            <input type="datetime-local" value={certValidFrom} onChange={(e) => setCertValidFrom(e.target.value)} required />
          </label>
          <ErrorBanner error={certError} />
          <button type="submit" disabled={!activeProviderId}>
            Add certification
          </button>
        </form>
      </section>
    </div>
  )
}
