import { useState } from 'react'
import { Link } from 'react-router-dom'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { listActions } from '../api/actions'

const STATUSES = ['validated', 'approved', 'submitted', 'confirmed', 'partially_confirmed', 'rejected', 'unknown']

export function ActionsListPage() {
  const { context } = useTempoContext()
  const [status, setStatus] = useState('')
  const { data, error, loading, reload } = useApi(() => listActions(context!, { status: status || undefined }), [context, status])

  return (
    <div className="page">
      <h1>Actions</h1>
      <div className="filters">
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <button onClick={reload}>Refresh</button>
      </div>

      <ErrorBanner error={error} />
      {loading && <p>Loading...</p>}
      {data && data.actions.length === 0 && <p>No actions yet — validate one from a completed run.</p>}
      {data && data.actions.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Action ID</th>
              <th>Type</th>
              <th>Recommendation</th>
              <th>Status</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {data.actions.map((action) => (
              <tr key={action.action_id}>
                <td>
                  <Link to={`/actions/${action.action_id}`}>{action.action_id}</Link>
                </td>
                <td>{action.action_type}</td>
                <td>{action.recommendation_id}</td>
                <td>
                  <StatusBadge status={action.status} />
                </td>
                <td>{new Date(action.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
