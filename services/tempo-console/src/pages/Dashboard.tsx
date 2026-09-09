import { useState } from 'react'
import { ErrorBanner } from '../components/ErrorBanner'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { getDataReadiness, getModelMonitoring, runDriftCheck } from '../api/monitoring'

const CAPABILITIES = ['forecast.demand', 'forecast.labour_requirement', 'optimize.mix', 'optimize.roster']

export function DashboardPage() {
  const { context } = useTempoContext()
  const [capability, setCapability] = useState(CAPABILITIES[3])
  const readiness = useApi(() => getDataReadiness(context!, capability), [context, capability])
  const monitoring = useApi(() => getModelMonitoring(context!), [context])
  const [driftResult, setDriftResult] = useState<string | null>(null)

  async function checkDrift() {
    setDriftResult(null)
    try {
      const result = await runDriftCheck(context!)
      setDriftResult(
        result.drift_signals.length === 0
          ? 'No drift detected.'
          : result.drift_signals.map((s) => `${s.run_type}: ${s.metric} ${s.baseline} -> ${s.recent}`).join('; '),
      )
    } catch (err) {
      setDriftResult(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <div className="page">
      <h1>Dashboard</h1>

      <section className="card">
        <h2>Data readiness</h2>
        <label>
          Capability
          <select value={capability} onChange={(e) => setCapability(e.target.value)}>
            {CAPABILITIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>
        <ErrorBanner error={readiness.error} />
        {readiness.loading && <p>Loading...</p>}
        {readiness.data && (
          <>
            <p>
              Status: <strong>{readiness.data.status}</strong> (score {readiness.data.score})
            </p>
            <ul>
              {readiness.data.required_domains.map((d) => (
                <li key={d.domain}>
                  {d.domain}: {d.status} {d.warning ? `— ${d.warning}` : ''}
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="card">
        <h2>Model monitoring</h2>
        <ErrorBanner error={monitoring.error} />
        {monitoring.loading && <p>Loading...</p>}
        {monitoring.data && Object.keys(monitoring.data.models).length === 0 && <p>No completed runs yet.</p>}
        {monitoring.data && Object.keys(monitoring.data.models).length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Run type</th>
                <th>Runs</th>
                <th>Solver gap rate</th>
                <th>Avg confidence</th>
                <th>Avg backtest MAPE</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(monitoring.data.models).map(([runType, m]) => (
                <tr key={runType}>
                  <td>{runType}</td>
                  <td>{m.run_count}</td>
                  <td>{m.solver_gap_rate}</td>
                  <td>{m.avg_confidence ?? '—'}</td>
                  <td>{m.avg_backtest_mape ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <button onClick={checkDrift}>Run drift check</button>
        {driftResult && <p className="hint">{driftResult}</p>}
      </section>
    </div>
  )
}
