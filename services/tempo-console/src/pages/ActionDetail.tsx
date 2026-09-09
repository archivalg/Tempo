import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { getAction, reconcileAction } from '../api/actions'

export function ActionDetailPage() {
  const { actionId } = useParams<{ actionId: string }>()
  const { context } = useTempoContext()
  const { data, error, loading, reload } = useApi(() => getAction(context!, actionId!), [context, actionId])
  const [reconcileError, setReconcileError] = useState<unknown>(null)

  async function handleReconcile() {
    setReconcileError(null)
    try {
      await reconcileAction(context!, actionId!)
      reload()
    } catch (err) {
      setReconcileError(err)
    }
  }

  const needsReconciliation = data?.status === 'unknown' || data?.status === 'partially_confirmed'

  return (
    <div className="page">
      <div className="page-header">
        <h1>Action {actionId}</h1>
        {data && <StatusBadge status={data.status} />}
      </div>

      <ErrorBanner error={error} />
      {loading && <p>Loading...</p>}

      {data && (
        <section className="card">
          <dl>
            <dt>Action type</dt>
            <dd>{data.action_type}</dd>
            <dt>Recommendation</dt>
            <dd>{data.recommendation_id}</dd>
            <dt>Target</dt>
            <dd>
              {data.target.system} / {data.target.connection_id} / {data.target.site_id}
            </dd>
            <dt>Approver</dt>
            <dd>{data.approver_id ?? '—'}</dd>
            <dt>Detail</dt>
            <dd>{data.detail ?? '—'}</dd>
            <dt>Updated</dt>
            <dd>{new Date(data.updated_at).toLocaleString()}</dd>
          </dl>

          {needsReconciliation && (
            <>
              <p className="hint">
                No real vendor writeback connector exists yet (see services/tempo-api README's Phase E section) — an
                <code> unknown</code> outcome needs reconciliation before any retry.
              </p>
              <button onClick={handleReconcile}>Reconcile</button>
              <ErrorBanner error={reconcileError} />
            </>
          )}
        </section>
      )}

      <Link to="/actions">Back to actions</Link>
    </div>
  )
}
