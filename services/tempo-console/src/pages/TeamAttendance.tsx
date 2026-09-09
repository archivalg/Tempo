import { useState } from 'react'
import { ErrorBanner } from '../components/ErrorBanner'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { getSiteAttendance } from '../api/attendance'

export function TeamAttendancePage() {
  const { context } = useTempoContext()
  const [siteId, setSiteId] = useState(context?.site_ids[0] ?? '')
  const [sinceHours, setSinceHours] = useState(24)
  const { data, error, loading, reload } = useApi(() => getSiteAttendance(context!, siteId, sinceHours), [context, siteId, sinceHours])

  const exceptions = data?.filter((row) => !row.matched_rostered_shift) ?? []

  return (
    <div className="page">
      <h1>Team attendance</h1>
      <p className="hint">
        Business Spec §8's Supervisor role: "cover shifts, manage exceptions, respond to live alerts."{' '}
        <code>matched_rostered_shift: false</code> is the exception signal — a starting point, not a full
        exception/alerting system (see services/tempo-api README's native capture section).
      </p>

      <div className="filters">
        <label>
          Site ID
          <input value={siteId} onChange={(e) => setSiteId(e.target.value)} />
        </label>
        <label>
          Since (hours)
          <input type="number" value={sinceHours} onChange={(e) => setSinceHours(Number(e.target.value))} min={1} />
        </label>
        <button onClick={reload}>Refresh</button>
      </div>

      <ErrorBanner error={error} />
      {loading && <p>Loading...</p>}

      {data && exceptions.length > 0 && (
        <section className="card exceptions">
          <h2>Exceptions ({exceptions.length})</h2>
          <ul>
            {exceptions.map((row) => (
              <li key={row.attendance_session_id}>
                Worker {row.worker_id} clocked in at {new Date(row.clocked_in_at).toLocaleString()} with no matching
                rostered shift.
              </li>
            ))}
          </ul>
        </section>
      )}

      {data && data.length === 0 && <p>No attendance sessions in this window.</p>}
      {data && data.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Worker</th>
              <th>Clocked in</th>
              <th>Clocked out</th>
              <th>Rostered?</th>
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr key={row.attendance_session_id} className={row.matched_rostered_shift ? undefined : 'exception-row'}>
                <td>{row.worker_id}</td>
                <td>{new Date(row.clocked_in_at).toLocaleString()}</td>
                <td>{row.clocked_out_at ? new Date(row.clocked_out_at).toLocaleString() : 'still clocked in'}</td>
                <td>{row.matched_rostered_shift ? 'yes' : 'no'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
