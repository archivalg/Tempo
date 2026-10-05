import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Banner, PageHead, Skeleton } from '../components/ui'
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
    <>
      <PageHead title={`Action ${actionId}`} sub="Validated writeback evidence, status and reconciliation.">
        {data && <StatusBadge status={data.status} />}
      </PageHead>

      {error ? <Banner tone="bad" title="Could not load action">{error instanceof Error ? error.message : String(error)}</Banner> : null}
      {loading && <Skeleton h={160} />}

      {data && (
        <section className="tp-card">
          <div className="tp-body">
          <dl className="tp-dl">
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
              <Banner tone="warn" title="Reconciliation required">No real vendor writeback connector exists yet. Unknown outcomes must be reconciled before any retry.</Banner>
              <button className="tp-btn primary" onClick={handleReconcile}>Reconcile</button>
              {reconcileError ? <Banner tone="bad" title="Could not reconcile">{reconcileError instanceof Error ? reconcileError.message : String(reconcileError)}</Banner> : null}
            </>
          )}
          </div>
        </section>
      )}

      <p><Link to="/actions">Back to actions</Link></p>
    </>
  )
}
