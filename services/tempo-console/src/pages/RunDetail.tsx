import { Link, useNavigate, useParams } from 'react-router-dom'
import { ErrorBanner } from '../components/ErrorBanner'
import { StatusBadge } from '../components/StatusBadge'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { cancelRun, getRun } from '../api/runs'
import { ACTION_TYPE_BY_RUN_TYPE } from '../api/types'

function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>
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
    <div className="page">
      <div className="page-header">
        <h1>Run {runId}</h1>
        {data && <StatusBadge status={data.status} />}
      </div>

      <ErrorBanner error={error} />
      {loading && <p>Loading...</p>}

      {data && !isTerminal && (
        <div className="card">
          <p>This run is not yet in a terminal state.</p>
          <button onClick={reload}>Refresh</button>
          <button onClick={handleCancel}>Cancel run</button>
        </div>
      )}

      {data && isTerminal && (
        <>
          <section className="card">
            <h2>Model</h2>
            <p>
              {data.model?.name} v{data.model?.version} ({data.model?.solver})
            </p>
          </section>

          {data.explanation && (
            <section className="card">
              <h2>Explanation</h2>
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
              <div className="columns">
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
            </section>
          )}

          <section className="card">
            <h2>Result</h2>
            <JsonBlock value={data.result} />
          </section>

          {actionType && (
            <section className="card">
              <h2>Take action</h2>
              {data.recommendation_id ? (
                <>
                  <p>
                    This run type maps to action_type <code>{actionType}</code>.
                  </p>
                  <button
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
                <p>No recommendation was recorded for this run — nothing to act on.</p>
              )}
            </section>
          )}
        </>
      )}

      <Link to="/runs">Back to runs</Link>
    </div>
  )
}
