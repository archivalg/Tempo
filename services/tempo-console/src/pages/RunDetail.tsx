import { Link, useNavigate, useParams } from 'react-router-dom'
import { Banner, Empty, PageHead, Skeleton } from '../components/ui'
import { StatusBadge } from '../components/StatusBadge'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { cancelRun, getRun } from '../api/runs'
import { ACTION_TYPE_BY_RUN_TYPE } from '../api/types'

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="tp-code">{JSON.stringify(value, null, 2)}</pre>
}

export function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const { context } = useTempoContext()
  const navigate = useNavigate()
  const { data, error, loading, reload } = useApi(() => getRun(context!, runId!), [context, runId])

  async function handleCancel() {
    await cancelRun(context!, runId!)
    reload()
  }

  const isTerminal = data?.status === 'completed' || data?.status === 'completed_with_warnings'
  const actionType = data?.run_type ? ACTION_TYPE_BY_RUN_TYPE[data.run_type] : undefined

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
