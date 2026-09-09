import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { listRuns } from '../api/runs'
import { RUN_TYPES } from '../api/types'

export function RunsListPage() {
  const { context } = useTempoContext()
  const [runType, setRunType] = useState('')
  const [status, setStatus] = useState('')
  const [cursor, setCursor] = useState<string | undefined>(undefined)
  const [history, setHistory] = useState<string[]>([])

  const { data, error, loading, reload } = useApi(
    () => listRuns(context!, { runType: runType || undefined, status: status || undefined, cursor }),
    [context, runType, status, cursor],
  )

  function resetPaging() {
    setCursor(undefined)
    setHistory([])
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Runs</h1>
        <Link className="button" to="/runs/new">
          New run
        </Link>
      </div>

      <div className="filters">
        <label>
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
        <label>
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
        <button onClick={reload}>Refresh</button>
      </div>

      <ErrorBanner error={error} />
      {loading && <p>Loading...</p>}
      {data && data.runs.length === 0 && <p>No runs yet — create one to get started.</p>}
      {data && data.runs.length > 0 && (
        <table>
          <thead>
            <tr>
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

      <div className="pager">
        <button disabled={history.length === 0} onClick={() => {
          const prev = [...history]
          const last = prev.pop()
          setHistory(prev)
          setCursor(last)
        }}>
          Previous
        </button>
        <button
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
    </div>
  )
}
