import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Banner, Empty, PageHead, Skeleton } from '../components/ui'
import { StatusBadge } from '../components/StatusBadge'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { listRuns } from '../api/runs'
import { RUN_TYPES } from '../api/types'

export function RunsListPage() {
  const { context } = useTempoContext()
  const navigate = useNavigate()
  const [runType, setRunType] = useState('')
  const [status, setStatus] = useState('')
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [history, setHistory] = useState<string[]>([])
  const [selected, setSelected] = useState<string[]>([])

  function toggleSelected(runId: string) {
    setSelected((current) => (current.includes(runId) ? current.filter((id) => id !== runId) : [...current, runId]))
  }

  const { data, error, loading, reload } = useApi(
    () => listRuns(context!, { runType: runType || undefined, status: status || undefined, cursor }),
    [context, runType, status, cursor],
  )

  function resetPaging() {
    setCursor(undefined)
    setHistory([])
  }

  return (
    <>
      <PageHead title="Optimisation Studio" sub="Advanced run history and comparisons. Everyday planning should start from Demand and Roster Planner.">
        <Link className="tp-btn primary" style={{ textDecoration: 'none' }} to="/runs/new">New run</Link>
      </PageHead>

      <section className="tp-card">
        <header><h2>Run history</h2><button className="tp-btn" onClick={reload}>Refresh</button></header>
        <div className="tp-body tp-row">
        <label className="tp-field">
          Run type
          <select
            value={runType}
            onChange={(e) => {
              setRunType(e.target.value)
              resetPaging()
            }}
          >
            <option value="">All</option>
            {RUN_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="tp-field">
          Status
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value)
              resetPaging()
            }}
          >
            <option value="">All</option>
            <option value="completed">completed</option>
            <option value="completed_with_warnings">completed_with_warnings</option>
            <option value="failed">failed</option>
          </select>
        </label>
        <button className="tp-btn" disabled={selected.length < 2} onClick={() => navigate('/runs/compare', { state: { runIds: selected } })}>
          Compare selected ({selected.length})
        </button>
        </div>

      {error ? <div className="tp-body"><Banner tone="bad" title="Could not load runs">{error instanceof Error ? error.message : String(error)}</Banner></div> : null}
      {loading && <div className="tp-body"><Skeleton h={180} /></div>}
      {data && data.runs.length === 0 && <Empty title="No runs yet">Create one from here only for advanced diagnostics; core roster generation lives in Roster Planner.</Empty>}
      {data && data.runs.length > 0 && (
        <table className="tp-table">
          <thead>
            <tr>
              <th></th>
              <th>Run ID</th>
              <th>Type</th>
              <th>Status</th>
              <th>Created</th>
              <th>Completed</th>
            </tr>
          </thead>
          <tbody>
            {data.runs.map((run) => (
              <tr key={run.run_id}>
                <td>
                  <input
                    type="checkbox"
                    aria-label={`Select ${run.run_id} for comparison`}
                    checked={selected.includes(run.run_id)}
                    onChange={() => toggleSelected(run.run_id)}
                  />
                </td>
                <td>
                  <Link to={`/runs/${run.run_id}`}>{run.run_id}</Link>
                </td>
                <td>{run.run_type}</td>
                <td>
                  <StatusBadge status={run.status} />
                </td>
                <td>{new Date(run.created_at).toLocaleString()}</td>
                <td>{run.completed_at ? new Date(run.completed_at).toLocaleString() : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className="tp-body tp-row">
        <button className="tp-btn" disabled={history.length === 0} onClick={() => {
          const prev = [...history]
          const last = prev.pop()
          setHistory(prev)
          setCursor(last)
        }}>
          Previous
        </button>
        <button className="tp-btn"
          disabled={!data?.next_cursor}
          onClick={() => {
            if (!data?.next_cursor) return
            setHistory((h) => [...h, cursor ?? ''])
            setCursor(data.next_cursor)
          }}
        >
          Next
        </button>
      </div>
      </section>
    </>
  )
}
