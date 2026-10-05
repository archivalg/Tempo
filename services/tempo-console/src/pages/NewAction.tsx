import { useState, type FormEvent } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Banner, PageHead, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { executeAction, validateAction } from '../api/actions'
import type { ActionValidateResponse } from '../api/types'

const ACTION_TYPES = ['publish_roster', 'update_assignment', 'approve_leave', 'create_training_plan']
// tempo_native is the one target system with a real, working writeback
// (app/maestro/native_writeback.py — Tempo committing to its own canonical
// tables for Standalone deployments); the rest are Overlay vendors that
// still honestly report 'unknown' since no real connector exists yet.
const SOURCE_SYSTEMS = ['deputy', 'ukg_pro_wfm', 'ukg_ready', 'wms', 'tempo_native']

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
    <>
      <PageHead title="New controlled action" sub="Validate first, then execute with an expiring action token and approval permission." />
      <Banner tone="info" title="Writeback boundary">Native Tempo publication is real. Overlay vendor writeback remains unknown unless a verified connector reconciles it.</Banner>
      <section className="tp-card">
        <header><h2>Validate action</h2></header>
      <form className="tp-body tp-stack" onSubmit={handleValidate}>
        <label className="tp-field">
          Action type
          <select value={actionType} onChange={(e) => setActionType(e.target.value)}>
            {ACTION_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label className="tp-field">
          Recommendation ID
          <input value={recommendationId} onChange={(e) => setRecommendationId(e.target.value)} required />
        </label>
        <div className="tp-cols2">
        <label className="tp-field">
          Target system
          <select value={system} onChange={(e) => setSystem(e.target.value)}>
            {SOURCE_SYSTEMS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="tp-field">
          Connection ID
          <input value={connectionId} onChange={(e) => setConnectionId(e.target.value)} required />
        </label>
        </div>
        <div className="tp-cols2">
        <label className="tp-field">
          Site ID
          <input value={siteId} onChange={(e) => setSiteId(e.target.value)} required />
        </label>
        <label className="tp-field">
          Expected source version (leave blank if this target has never been written to)
          <input value={expectedSourceVersion} onChange={(e) => setExpectedSourceVersion(e.target.value)} />
        </label>
        </div>
        {error ? <Banner tone="bad" title="Action failed">{error instanceof Error ? error.message : String(error)}</Banner> : null}
        <button className="tp-btn primary" type="submit" disabled={busy}>
          Validate
        </button>
      </form>
      </section>

      {validated && (
        <section className="tp-card" style={{ marginTop: 16 }}>
          <header><h2>Validated impact</h2><Status tone="risk">Token expires {new Date(validated.expires_at).toLocaleString()}</Status></header>
          <div className="tp-body tp-stack">
          <pre className="tp-code">{JSON.stringify(validated.impact_summary, null, 2)}</pre>
          <p>Token expires: {new Date(validated.expires_at).toLocaleString()}</p>
          <button className="tp-btn primary" onClick={handleExecute} disabled={busy || !!executeResult}>
            Execute (requires labour.approve)
          </button>
          </div>
        </section>
      )}

      {executeResult && (
        <section className="tp-card" style={{ marginTop: 16 }}>
          <header><h2>Execution result</h2><Status tone={executeResult.status === 'confirmed' ? 'ok' : executeResult.status === 'unknown' ? 'risk' : 'neutral'}>{executeResult.status}</Status></header>
          <div className="tp-body">
            {executeResult.detail && <p>{executeResult.detail}</p>}
            <button className="tp-btn" onClick={() => navigate(`/actions/${validated?.action_id}`)}>View action</button>
          </div>
        </section>
      )}
    </>
  )
}
