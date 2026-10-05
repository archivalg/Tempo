import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Banner, Empty, PageHead, Skeleton } from '../components/ui'
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
    <>
      <PageHead title="Controlled actions" sub="Validated writeback and reconciliation history. Native publication uses Roster Planner for everyday work.">
        <Link className="tp-btn primary" style={{ textDecoration: 'none' }} to="/actions/new">New action</Link>
      </PageHead>
      <section className="tp-card">
        <header><h2>Action history</h2><button className="tp-btn" onClick={reload}>Refresh</button></header>
        <div className="tp-body tp-row">
          <label className="tp-field">
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
        </div>

      {error ? <div className="tp-body"><Banner tone="bad" title="Could not load actions">{error instanceof Error ? error.message : String(error)}</Banner></div> : null}
      {loading && <div className="tp-body"><Skeleton h={160} /></div>}
      {data && data.actions.length === 0 && <Empty title="No actions yet">Validate one from a completed run, or publish native rosters from Roster Planner.</Empty>}
      {data && data.actions.length > 0 && (
        <table className="tp-table">
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
      </section>
    </>
  )
}
