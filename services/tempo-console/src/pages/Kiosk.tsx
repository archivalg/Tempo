import { useState, type FormEvent } from 'react'
import { ErrorBanner } from '../components/ErrorBanner'
import { useTempoContext } from '../context/TempoContextProvider'
import { clockIn, clockOut, getWorkerShifts, whoami } from '../api/attendance'
import type { UpcomingShift, WhoamiResponse } from '../api/types'

export function KioskPage() {
  const { context } = useTempoContext()
  const [pin, setPin] = useState('')
  const [siteId, setSiteId] = useState(context?.site_ids[0] ?? '')
  const [worker, setWorker] = useState<WhoamiResponse | null>(null)
  const [shifts, setShifts] = useState<UpcomingShift[] | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  async function identify(event?: FormEvent) {
    event?.preventDefault()
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const result = await whoami(context!, { method: 'pin', pin })
      setWorker(result)
      setShifts(await getWorkerShifts(context!, result.worker_id))
    } catch (err) {
      setWorker(null)
      setShifts(null)
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function handleClockIn() {
    setBusy(true)
    setError(null)
    try {
      const result = await clockIn(context!, siteId, { method: 'pin', pin })
      setMessage(
        `Clocked in at ${new Date(result.clocked_in_at).toLocaleTimeString()}` +
          (result.matched_rostered_shift ? '' : ' — no matching rostered shift found for this time'),
      )
      await identify()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  async function handleClockOut() {
    setBusy(true)
    setError(null)
    try {
      const result = await clockOut(context!, { method: 'pin', pin })
      setMessage(`Clocked out. Shift duration: ${result.duration_minutes.toFixed(0)} minutes.`)
      await identify()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page kiosk">
      <h1>Kiosk</h1>
      <p className="hint">
        Business Spec §4/§5's Standalone "Time &amp; Attendance (native capture)" — no worker login exists yet, so a
        PIN identifies you the same way a physical clock-in terminal would. This page carries the console session's
        own tenant/site context; the PIN is what says who you are.
      </p>

      <form onSubmit={identify}>
        <label>
          Site ID
          <input value={siteId} onChange={(e) => setSiteId(e.target.value)} required />
        </label>
        <label>
          PIN
          <input value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric" required />
        </label>
        <ErrorBanner error={error} />
        <button type="submit" disabled={busy || !pin}>
          Identify
        </button>
      </form>

      {worker && (
        <section className="card">
          <h2>
            Worker {worker.worker_id} ({worker.employment_type}, home site {worker.home_site})
          </h2>
          <p>{worker.has_open_session ? 'Currently clocked in.' : 'Not currently clocked in.'}</p>
          {message && <p className="hint">{message}</p>}
          {worker.has_open_session ? (
            <button onClick={handleClockOut} disabled={busy}>
              Clock out
            </button>
          ) : (
            <button onClick={handleClockIn} disabled={busy}>
              Clock in
            </button>
          )}

          {shifts && (
            <>
              <h3>Upcoming / recent shifts</h3>
              {shifts.length === 0 && <p>No shifts on record.</p>}
              {shifts.length > 0 && (
                <table>
                  <thead>
                    <tr>
                      <th>Role</th>
                      <th>Zone</th>
                      <th>Start</th>
                      <th>End</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {shifts.map((shift) => (
                      <tr key={shift.shift_id}>
                        <td>{shift.role}</td>
                        <td>{shift.zone}</td>
                        <td>{new Date(shift.start_at).toLocaleString()}</td>
                        <td>{new Date(shift.end_at).toLocaleString()}</td>
                        <td>{shift.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </section>
      )}
    </div>
  )
}
