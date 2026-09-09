import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ErrorBanner } from '../components/ErrorBanner'
import { useTempoContext } from '../context/TempoContextProvider'
import { executeAction, validateAction } from '../api/actions'
import type { ActionValidateResponse } from '../api/types'

const ACTION_TYPES = ['publish_roster', 'update_assignment', 'approve_leave', 'create_training_plan']
const SOURCE_SYSTEMS = ['deputy', 'ukg_pro_wfm', 'ukg_ready', 'wms']

export function NewActionPage() {
  const { context } = useTempoContext()
  const navigate = useNavigate()
  const location = useLocation()
  const navState = (location.state ?? {}) as { recommendationId?: string; actionType?: string }

  const [actionType, setActionType] = useState(navState.actionType ?? ACTION_TYPES[0])
  const [recommendationId, setRecommendationId] = useState(navState.recommendationId ?? '')
  const [system, setSystem] = useState(SOURCE_SYSTEMS[0])
  const [connectionId, setConnectionId] = useState('con_1')
  const [siteId, setSiteId] = useState(context?.site_ids[0] ?? '')
  const [expectedSourceVersion, setExpectedSourceVersion] = useState('')

  const [validated, setValidated] = useState<ActionValidateResponse | null>(null)
  const [executeResult, setExecuteResult] = useState<{ status: string; detail: string | null } | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  function currentBody() {
    return {
      action_type: actionType,
      recommendation_id: recommendationId,
      target: { system, connection_id: connectionId, site_id: siteId },
      expected_source_version: expectedSourceVersion || null,
    }
  }

  async function handleValidate(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    setValidated(null)
    setExecuteResult(null)
    try {
      const response = await validateAction(context!, currentBody())
      setValidated(response)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function handleExecute() {
    if (!validated) return
    setBusy(true)
    setError(null)
    try {
      const response = await executeAction(context!, {
        ...currentBody(),
        action_id: validated.action_id,
        action_token: validated.action_token,
      })
      setExecuteResult(response)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <h1>New action</h1>
      <p className="hint">
        §12's two-step contract: validate previews the impact and issues a short-lived token; execute (requires
        labour.approve) submits it. See services/tempo-api README's Phase E section — there is no real vendor
        writeback connector yet, so execute will honestly report <code>unknown</code> unless reconciled later.
      </p>
      <form onSubmit={handleValidate}>
        <label>
          Action type
          <select value={actionType} onChange={(e) => setActionType(e.target.value)}>
            {ACTION_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label>
          Recommendation ID
          <input value={recommendationId} onChange={(e) => setRecommendationId(e.target.value)} required />
        </label>
        <label>
          Target system
          <select value={system} onChange={(e) => setSystem(e.target.value)}>
            {SOURCE_SYSTEMS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Connection ID
          <input value={connectionId} onChange={(e) => setConnectionId(e.target.value)} required />
        </label>
        <label>
          Site ID
          <input value={siteId} onChange={(e) => setSiteId(e.target.value)} required />
        </label>
        <label>
          Expected source version (leave blank if this target has never been written to)
          <input value={expectedSourceVersion} onChange={(e) => setExpectedSourceVersion(e.target.value)} />
        </label>
        <ErrorBanner error={error} />
        <button type="submit" disabled={busy}>
          Validate
        </button>
      </form>

      {validated && (
        <section className="card">
          <h2>Validated — impact summary</h2>
          <pre className="json-block">{JSON.stringify(validated.impact_summary, null, 2)}</pre>
          <p>Token expires: {new Date(validated.expires_at).toLocaleString()}</p>
          <button onClick={handleExecute} disabled={busy || !!executeResult}>
            Execute (requires labour.approve)
          </button>
        </section>
      )}

      {executeResult && (
        <section className="card">
          <h2>Execution result</h2>
          <p>
            Status: <strong>{executeResult.status}</strong>
          </p>
          {executeResult.detail && <p>{executeResult.detail}</p>}
          <button onClick={() => navigate(`/actions/${validated?.action_id}`)}>View action</button>
        </section>
      )}
    </div>
  )
}
