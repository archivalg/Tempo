import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Banner, PageHead } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { createRun } from '../api/runs'
import { OBJECTIVE_PROFILES, RUN_TYPES, type ObjectiveProfile, type RunType } from '../api/types'

function isoInDays(days: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() + days)
  d.setUTCHours(0, 0, 0, 0)
  return d.toISOString().slice(0, 16)
}

export function NewRunPage() {
  const { context } = useTempoContext()
  const navigate = useNavigate()
  const [runType, setRunType] = useState<RunType>('demand_forecast')
  const [siteIds, setSiteIds] = useState(context?.site_ids.join(', ') ?? '')
  const [customerIds, setCustomerIds] = useState(context?.customer_ids.join(', ') ?? '')
  const [windowStart, setWindowStart] = useState(isoInDays(0))
  const [windowEnd, setWindowEnd] = useState(isoInDays(7))
  const [objectiveProfile, setObjectiveProfile] = useState<ObjectiveProfile>('balanced')
  const [committed, setCommitted] = useState(false)
  const [demandMode, setDemandMode] = useState<'known_orders' | 'forecast_only' | 'hybrid'>('known_orders')
  const [forecastBasis, setForecastBasis] = useState<'total' | 'additional'>('total')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const isOrderFulfillment = runType === 'order_fulfillment'

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (submitting) return
    setSubmitting(true)
    setError(null)
    try {
      const response = await createRun(context!, {
        runType,
        siteIds: siteIds.split(',').map((s) => s.trim()).filter(Boolean),
        customerIds: customerIds.split(',').map((s) => s.trim()).filter(Boolean),
        windowStart: new Date(windowStart).toISOString(),
        windowEnd: new Date(windowEnd).toISOString(),
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        bucketMinutes: 60,
        objectiveProfile,
        ...(isOrderFulfillment ? { committed, demandMode, ...(demandMode === 'hybrid' ? { forecastBasis } : {}) } : {}),
      })
      navigate(`/runs/${response.run_id}`)
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <PageHead title="New optimisation run" sub="Advanced diagnostic run creation. Roster generation for normal planning is available in Roster Planner." />
      <section className="tp-card">
        <header><h2>Run parameters</h2></header>
      <form className="tp-body tp-stack" onSubmit={handleSubmit}>
        <label className="tp-field">
          Run type
          <select value={runType} onChange={(e) => setRunType(e.target.value as RunType)}>
            {RUN_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <div className="tp-cols2">
        <label className="tp-field">
          Site IDs (comma-separated, at least one required)
          <input value={siteIds} onChange={(e) => setSiteIds(e.target.value)} required />
        </label>
        <label className="tp-field">
          Customer IDs (comma-separated, optional)
          <input value={customerIds} onChange={(e) => setCustomerIds(e.target.value)} />
        </label>
        </div>
        <div className="tp-cols2">
        <label className="tp-field">
          Window start
          <input type="datetime-local" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} required />
        </label>
        <label className="tp-field">
          Window end
          <input type="datetime-local" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} required />
        </label>
        </div>
        <label className="tp-field">
          Objective profile
          <select value={objectiveProfile} onChange={(e) => setObjectiveProfile(e.target.value as ObjectiveProfile)}>
            {OBJECTIVE_PROFILES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        {isOrderFulfillment && (
          <div className="tp-stack" style={{ border: '1px solid var(--tp-border, #ddd)', borderRadius: 8, padding: 12 }}>
            <div className="tp-cols2">
              <label className="tp-field">
                Demand basis
                <select value={demandMode} onChange={(e) => setDemandMode(e.target.value as typeof demandMode)}>
                  <option value="known_orders">Known orders only</option>
                  <option value="forecast_only">Forecast only</option>
                  <option value="hybrid">Known orders + forecast for the rest</option>
                </select>
              </label>
              {demandMode === 'hybrid' && (
                <label className="tp-field">
                  Forecast basis
                  <select value={forecastBasis} onChange={(e) => setForecastBasis(e.target.value as typeof forecastBasis)}>
                    <option value="total">Forecast is the total demand</option>
                    <option value="additional">Forecast is on top of known orders</option>
                  </select>
                </label>
              )}
            </div>
            <label className="tp-field" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" checked={committed} onChange={(e) => setCommitted(e.target.checked)} />
              Commit this plan
            </label>
            <p className="tp-muted" style={{ margin: 0, fontSize: 12.5 }}>
              {committed
                ? 'A committed run reserves the workers and order quantity it allocates. No other committed run or published roster can reuse that reserved time until this plan is released. Use this once you are ready to act on the plan.'
                : 'A draft run does not reserve anything — it is safe to run as many times as you like to compare options. Nothing is committed until you create a committed run.'}
            </p>
          </div>
        )}
        {error ? <Banner tone="bad" title="Could not create run">{error instanceof Error ? error.message : String(error)}</Banner> : null}
        <button className="tp-btn primary" type="submit" disabled={submitting}>
          {submitting ? 'Submitting...' : 'Create run'}
        </button>
      </form>
      </section>
    </>
  )
}
