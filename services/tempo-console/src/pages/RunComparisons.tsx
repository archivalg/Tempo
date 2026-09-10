import { useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { ErrorBanner } from '../components/ErrorBanner'
import { useTempoContext } from '../context/TempoContextProvider'
import { compareRuns } from '../api/runs'
import type { RunComparisonResponse } from '../api/types'

function formatKpiValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>
    if ('amount' in record && 'currency' in record) return `${record.amount} ${record.currency}`
    return JSON.stringify(value)
  }
  return String(value)
}

export function RunComparisonsPage() {
  const { context } = useTempoContext()
  const location = useLocation()
  const navState = (location.state ?? {}) as { runIds?: string[] }

  const [runIdsInput, setRunIdsInput] = useState((navState.runIds ?? []).join(', '))
  const [result, setResult] = useState<RunComparisonResponse | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function handleCompare(event: FormEvent) {
    event.preventDefault()
    const runIds = runIdsInput
      .split(',')
      .map((id) => id.trim())
      .filter(Boolean)
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setResult(await compareRuns(context!, runIds))
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  const kpiKeys = result ? Array.from(new Set(result.kpis.flatMap((r) => Object.keys(r.kpis)))) : []

  return (
    <div className="page">
      <h1>Compare runs</h1>
      <p className="hint">
        Runs must be in a comparable terminal state (<code>completed</code> or{' '}
        <code>completed_with_warnings</code>). A <code>margin_3pl</code> run's KPIs are only visible with{' '}
        <code>labour.margin.read</code> — same restriction as the Run detail page.
      </p>

      <form onSubmit={handleCompare}>
        <label>
          Run IDs (comma-separated, at least two)
          <input value={runIdsInput} onChange={(e) => setRunIdsInput(e.target.value)} required />
        </label>
        <ErrorBanner error={error} />
        <button type="submit" disabled={busy}>
          Compare
        </button>
      </form>

      {result && (
        <section className="card">
          <h2>KPIs</h2>
          <table>
            <thead>
              <tr>
                <th>KPI</th>
                {result.kpis.map((r) => (
                  <th key={r.run_id}>
                    <Link to={`/runs/${r.run_id}`}>{r.run_id}</Link>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {kpiKeys.map((key) => (
                <tr key={key}>
                  <td>{key}</td>
                  {result.kpis.map((r) => (
                    <td key={r.run_id}>{formatKpiValue(r.kpis[key])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <Link to="/runs">Back to runs</Link>
    </div>
  )
}
