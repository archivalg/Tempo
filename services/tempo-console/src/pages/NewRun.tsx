import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { ErrorBanner } from '../components/ErrorBanner'
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
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
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
      })
      navigate(`/runs/${response.run_id}`)
    } catch (err) {
      setError(err)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page">
      <h1>New run</h1>
      <form onSubmit={handleSubmit}>
        <label>
          Run type
          <select value={runType} onChange={(e) => setRunType(e.target.value as RunType)}>
            {RUN_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <label>
          Site IDs (comma-separated, at least one required)
          <input value={siteIds} onChange={(e) => setSiteIds(e.target.value)} required />
        </label>
        <label>
          Customer IDs (comma-separated, optional)
          <input value={customerIds} onChange={(e) => setCustomerIds(e.target.value)} />
        </label>
        <label>
          Window start
          <input type="datetime-local" value={windowStart} onChange={(e) => setWindowStart(e.target.value)} required />
        </label>
        <label>
          Window end
          <input type="datetime-local" value={windowEnd} onChange={(e) => setWindowEnd(e.target.value)} required />
        </label>
        <label>
          Objective profile
          <select value={objectiveProfile} onChange={(e) => setObjectiveProfile(e.target.value as ObjectiveProfile)}>
            {OBJECTIVE_PROFILES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <ErrorBanner error={error} />
        <button type="submit" disabled={submitting}>
          {submitting ? 'Submitting...' : 'Create run'}
        </button>
      </form>
    </div>
  )
}
