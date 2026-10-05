import { useState, type FormEvent } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Banner, PageHead } from '../components/ui'
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
    <>
      <PageHead title="Compare runs" sub="Compare terminal optimisation results with the same permission gates as run detail." />
      <Banner tone="info" title="Comparable runs only">Runs must be completed or completed with warnings. Margin KPIs remain hidden without the required permission.</Banner>

      <section className="tp-card" style={{ marginBottom: 16 }}>
        <header><h2>Selection</h2></header>
      <form className="tp-body tp-stack" onSubmit={handleCompare}>
        <label className="tp-field">
          Run IDs (comma-separated, at least two)
          <input value={runIdsInput} onChange={(e) => setRunIdsInput(e.target.value)} required />
        </label>
        {error ? <Banner tone="bad" title="Could not compare runs">{error instanceof Error ? error.message : String(error)}</Banner> : null}
        <button className="tp-btn primary" type="submit" disabled={busy}>
          Compare
        </button>
      </form>
      </section>

      {result && (
        <section className="tp-card">
          <header><h2>KPIs</h2></header>
          <table className="tp-table">
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

      <p><Link to="/runs">Back to runs</Link></p>
    </>
  )
}
