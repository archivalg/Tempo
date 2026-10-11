import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Banner, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { StatusBadge } from '../components/StatusBadge'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { cancelRun, getRun, recommitRun, releaseCommitment } from '../api/runs'
import { completeOrder, getOrder } from '../api/orders'
import { ACTION_TYPE_BY_RUN_TYPE, type OrderFulfillmentResult } from '../api/types'
import { fmtNum } from '../lib/format'

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="tp-code">{JSON.stringify(value, null, 2)}</pre>
}

function OrderLifecyclePanel({ orderRef }: { orderRef: string }) {
  const { data, error, loading, reload } = useApi(() => getOrder(orderRef), [orderRef])
  const [qty, setQty] = useState('')
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)
  const [confirmed, setConfirmed] = useState<number | null>(null)

  async function confirm() {
    if (busy) return
    const quantity = Number(qty)
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setActionError(new Error('Enter a quantity greater than zero.'))
      return
    }
    setBusy(true)
    setActionError(null)
    try {
      const res = await completeOrder(orderRef, quantity)
      setConfirmed(res.confirmed_this_call)
      setQty('')
      reload()
    } catch (err) {
      setActionError(err)
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <Skeleton h={60} />
  if (error) return <Banner tone="bad" title={`Could not load order ${orderRef}`}>{error instanceof Error ? error.message : String(error)}</Banner>
  if (!data) return null

  return (
    <div className="tp-body" role="group" aria-label={`Order ${data.order_ref}`} style={{ borderTop: '1px solid var(--tp-border, #eee)', paddingTop: 10, marginTop: 10 }}>
      <p style={{ margin: '0 0 6px', fontWeight: 600 }}>{data.order_ref} <Status tone="neutral">{data.status}</Status></p>
      <div className="tp-cols2" style={{ marginBottom: 8 }}>
        <span>Total units: <strong>{fmtNum(data.units)}</strong></span>
        <span>Outstanding (not yet completed): <strong>{fmtNum(data.outstanding_quantity)}</strong></span>
        <span>Committed to a plan: <strong>{fmtNum(data.committed_units)}</strong></span>
        <span>Available for planning: <strong>{fmtNum(data.available_for_planning)}</strong></span>
        <span>Actually completed so far: <strong>{fmtNum(data.fulfilled_units)}</strong></span>
      </div>
      {actionError ? <Banner tone="bad" title="Could not confirm completion">{actionError instanceof Error ? actionError.message : String(actionError)}</Banner> : null}
      {confirmed != null && <Banner tone="info" title="Recorded">Confirmed {fmtNum(confirmed)} units completed for {data.order_ref}.</Banner>}
      <div className="tp-row" style={{ alignItems: 'center' }}>
        <label className="tp-field" style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
          Confirm units completed
          <input type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} style={{ width: 100 }} />
        </label>
        <button className="tp-btn" disabled={busy || !qty} onClick={() => void confirm()}>
          {busy ? 'Confirming…' : 'Confirm completion'}
        </button>
      </div>
      <p className="tp-muted" style={{ margin: '6px 0 0', fontSize: 12 }}>
        This records real, physical completion — it does not change what a plan has committed, and it cannot be used to mark more than this order's outstanding quantity as done.
      </p>
    </div>
  )
}

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const { context } = useTempoContext()
  const navigate = useNavigate()
  const { data, error, loading, reload } = useApi(() => getRun(context!, runId!), [context, runId])
  const [committing, setCommitting] = useState(false)
  const [releasing, setReleasing] = useState(false)
  const [lifecycleError, setLifecycleError] = useState<unknown>(null)
  const [released, setReleased] = useState<{ orders: number; workers: number } | null>(null)

  async function handleCancel() {
    await cancelRun(context!, runId!)
    reload()
  }

  async function handleCommit() {
    if (committing || !data?.run_type || !data.request) return
    setCommitting(true)
    setLifecycleError(null)
    try {
      const res = await recommitRun(context!, data.run_type as Parameters<typeof recommitRun>[1], data.request)
      navigate(`/runs/${res.run_id}`)
    } catch (err) {
      setLifecycleError(err)
      setCommitting(false)
    }
  }

  async function handleRelease() {
    if (releasing) return
    setReleasing(true)
    setLifecycleError(null)
    try {
      const res = await releaseCommitment(context!, runId!)
      setReleased({ orders: res.released.length, workers: res.released_worker_commitments.length })
      reload()
    } catch (err) {
      setLifecycleError(err)
    } finally {
      setReleasing(false)
    }
  }

  const isTerminal = data?.status === 'completed' || data?.status === 'completed_with_warnings'
  const actionType = data?.run_type ? ACTION_TYPE_BY_RUN_TYPE[data.run_type] : undefined
  const isOrderFulfillment = data?.run_type === 'order_fulfillment'
  const orderResult = isOrderFulfillment ? (data?.result as unknown as OrderFulfillmentResult | undefined) : undefined

  return (
    <>
      <PageHead title={`Run ${runId}`} sub="Model evidence, result payload and controlled action handoff.">
        {data && <StatusBadge status={data.status} />}
      </PageHead>

      {error ? <Banner tone="bad" title="Could not load run">{error instanceof Error ? error.message : String(error)}</Banner> : null}
      {loading && <Skeleton h={220} />}

      {data && !isTerminal && (
        <section className="tp-card">
          <div className="tp-body tp-stack">
          <p>This run is not yet in a terminal state.</p>
          <div className="tp-row"><button className="tp-btn" onClick={reload}>Refresh</button><button className="tp-btn danger" onClick={handleCancel}>Cancel run</button></div>
          </div>
        </section>
      )}

      {data && isTerminal && (
        <>
          <section className="tp-card">
            <header><h2>Model</h2></header>
            <div className="tp-body"><p>
              {data.model?.name} v{data.model?.version} ({data.model?.solver})
            </p></div>
          </section>

          {data.explanation && (
            <section className="tp-card" style={{ marginTop: 16 }}>
              <header><h2>Explanation</h2></header>
              <div className="tp-body">
              <p>
                Confidence: <strong>{data.explanation.confidence.score}</strong> ({data.explanation.confidence.band})
              </p>
              <p>Feasibility: {data.explanation.feasibility}</p>
              {data.explanation.primary_drivers.length > 0 && (
                <>
                  <h3>Primary drivers</h3>
                  <ul>
                    {data.explanation.primary_drivers.map((d, i) => (
                      <li key={i}>{d}</li>
                    ))}
                  </ul>
                </>
              )}
              {data.explanation.missing_evidence.length > 0 && (
                <>
                  <h3>Missing evidence</h3>
                  <ul>
                    {data.explanation.missing_evidence.map((d, i) => (
                      <li key={i}>{d}</li>
                    ))}
                  </ul>
                </>
              )}
              <div className="tp-cols2">
                <div>
                  <h3>Baseline</h3>
                  <JsonBlock value={data.explanation.baseline} />
                </div>
                <div>
                  <h3>Proposed</h3>
                  <JsonBlock value={data.explanation.proposed} />
                </div>
                <div>
                  <h3>Delta</h3>
                  <JsonBlock value={data.explanation.delta} />
                </div>
              </div>
              </div>
            </section>
          )}

          {isOrderFulfillment && (
            <section className="tp-card" aria-label="Commitment" style={{ marginTop: 16 }}>
              <header><h2>Commitment</h2></header>
              <div className="tp-body tp-stack">
                {lifecycleError ? <Banner tone="bad" title="Could not complete that action">{lifecycleError instanceof Error ? lifecycleError.message : String(lifecycleError)}</Banner> : null}
                {released && <Banner tone="info" title="Released">Released {released.orders} order allocation{released.orders === 1 ? '' : 's'} and {released.workers} worker reservation{released.workers === 1 ? '' : 's'}. The capacity and order quantity this run held are available again; nothing already completed was changed.</Banner>}
                {data.committed && !released ? (
                  <>
                    <p style={{ margin: 0 }}>
                      This is a <strong>committed</strong> plan. It has reserved the workers and order quantity it allocated — no other committed run or published roster can reuse that time until it is released.
                    </p>
                    <div className="tp-row">
                      <button className="tp-btn danger" disabled={releasing} onClick={() => void handleRelease()}>
                        {releasing ? 'Releasing…' : 'Release this commitment'}
                      </button>
                    </div>
                  </>
                ) : data.committed && released ? (
                  <p style={{ margin: 0 }}>
                    This run was committed but its reservation has since been <strong>released</strong> —
                    it no longer holds any worker time or order quantity, the same as a draft.
                  </p>
                ) : (
                  <>
                    <p style={{ margin: 0 }}>
                      This is a <strong>draft</strong> plan — it reserved nothing. Committing it will claim the workers and order quantity it allocated, so re-running it later may see less capacity available.
                    </p>
                    <div className="tp-row">
                      <button className="tp-btn primary" disabled={committing || !data.request} onClick={() => void handleCommit()}>
                        {committing ? 'Committing…' : 'Commit this plan'}
                      </button>
                    </div>
                    {!data.request && <p className="tp-muted" style={{ margin: 0, fontSize: 12 }}>This older run has no stored request to recommit from.</p>}
                  </>
                )}
              </div>
            </section>
          )}

          {isOrderFulfillment && orderResult && (
            <section className="tp-card" style={{ marginTop: 16 }}>
              <header><h2>Orders</h2></header>
              <div className="tp-body tp-stack">
                <table className="tp-table" aria-label="Orders in this run">
                  <thead><tr><th>Order</th><th>Source</th><th>Due</th><th>Quantity</th><th>On time</th><th>Shortfall</th></tr></thead>
                  <tbody>
                    {orderResult.orders.map((o) => (
                      <tr key={o.order_ref}>
                        <td>{o.order_ref}</td>
                        <td>{o.source}</td>
                        <td>{o.despatch_due}</td>
                        <td>{fmtNum(o.quantity)}</td>
                        <td><Status tone={o.on_time ? 'ok' : 'risk'}>{o.on_time ? 'Yes' : 'No'}</Status></td>
                        <td>{o.shortfall_quantity > 0 ? <Status tone="bad">{fmtNum(o.shortfall_quantity)}</Status> : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {orderResult.orders.filter((o) => o.source === 'order').map((o) => (
                  <OrderLifecyclePanel key={o.order_ref} orderRef={o.order_ref} />
                ))}
              </div>
            </section>
          )}

          <section className="tp-card" style={{ marginTop: 16 }}>
            <header><h2>Result</h2></header>
            <div className="tp-body">
            <JsonBlock value={data.result} />
            </div>
          </section>

          {actionType && (
            <section className="tp-card" style={{ marginTop: 16 }}>
              <header><h2>Take action</h2></header>
              <div className="tp-body">
              {data.recommendation_id ? (
                <>
                  <p>
                    This run type maps to action_type <code>{actionType}</code>.
                  </p>
                  <button className="tp-btn primary"
                    onClick={() =>
                      navigate('/actions/new', {
                        state: { recommendationId: data.recommendation_id, actionType },
                      })
                    }
                  >
                    Start action from this run
                  </button>
                </>
              ) : (
                <Empty title="No recommendation recorded">There is nothing to act on from this run.</Empty>
              )}
              </div>
            </section>
          )}
        </>
      )}

      <p><Link to="/runs">Back to runs</Link></p>
    </>
  )
}
