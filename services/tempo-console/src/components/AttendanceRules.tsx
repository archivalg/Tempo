import { useCallback, useEffect, useState } from 'react'
import { getAttendancePolicy, getGeofence, putAttendancePolicy, putGeofence, type PolicyInput } from '../api/ops'
import { ApiError } from '../api/client'
import { Banner, Skeleton, Status } from './ui'

/** The site's attendance rules. Nothing is implied: an unsaved site shows Tempo's defaults and says so. */
function Fence({ siteId, canEdit, onChange }: { siteId: string; canEdit: boolean; onChange: (configured: boolean) => void }) {
  const [g, setG] = useState({ lat: '', lon: '', radius: '200' })
  const [configured, setConfigured] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { getGeofence(siteId).then((x) => { setConfigured(x.configured); onChange(x.configured); if (x.configured) setG({ lat: String(x.latitude), lon: String(x.longitude), radius: String(x.radius_meters) }) }).catch((e) => setMsg(e.message)) }, [siteId, onChange])
  const here = () => {
    setMsg('Asking this browser for its position…')
    navigator.geolocation?.getCurrentPosition((p) => { setG((v) => ({ ...v, lat: p.coords.latitude.toFixed(6), lon: p.coords.longitude.toFixed(6) })); setMsg(`Filled from this device (accurate to about ${Math.round(p.coords.accuracy)} m). Check it, then save.`) },
      () => setMsg('This browser would not share its position. Type the coordinates instead.'), { enableHighAccuracy: true, timeout: 10000 })
  }
  async function save() {
    setBusy(true); setMsg(null)
    try { await putGeofence(siteId, { latitude: Number(g.lat), longitude: Number(g.lon), radius_meters: Number(g.radius) }); setConfigured(true); onChange(true); setMsg('Geofence saved.') } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Could not save') } finally { setBusy(false) }
  }
  return (
    <fieldset className="tp-stack" disabled={!canEdit} style={{ border: 0, padding: 0, margin: 0 }}>
      <h3 style={{ margin: '8px 0 0', fontSize: 14 }}>Site geofence {configured ? <Status tone="ok">Set</Status> : <Status tone="risk">Not set</Status>}</h3>
      <div className="tp-cols2">
        <label className="tp-field">Latitude<input inputMode="decimal" value={g.lat} onChange={(e) => setG({ ...g, lat: e.target.value })} placeholder="-37.8136" /></label>
        <label className="tp-field">Longitude<input inputMode="decimal" value={g.lon} onChange={(e) => setG({ ...g, lon: e.target.value })} placeholder="144.9631" /></label>
      </div>
      <label className="tp-field">Radius (metres, 25–5000)<input type="number" min={25} max={5000} value={g.radius} onChange={(e) => setG({ ...g, radius: e.target.value })} /></label>
      {canEdit && <div className="tp-row"><button type="button" className="tp-btn" onClick={here}>Use this device’s position</button>
        <button type="button" className="tp-btn" disabled={busy || !g.lat || !g.lon} onClick={() => void save()}>Save geofence</button></div>}
      {msg && <p role="status" className="tp-muted" style={{ fontSize: 13 }}>{msg}</p>}
    </fieldset>
  )
}

export function AttendanceRules({ siteId, canEdit }: { siteId: string; canEdit: boolean }) {
  const [f, setF] = useState<PolicyInput | null>(null)
  const [meta, setMeta] = useState<{ is_default: boolean; updated_by: string | null } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [fenced, setFenced] = useState(false)
  const onFence = useCallback((v: boolean) => setFenced(v), [])
  useEffect(() => {
    setF(null)
    getAttendancePolicy(siteId).then((p) => { const { site_id: _s, is_default, updated_by, updated_at: _u, ...rest } = p; void _s; void _u; setF(rest); setMeta({ is_default, updated_by }) }).catch((e) => setErr(e.message))
  }, [siteId])
  if (!f) return err ? <Banner tone="bad" title="Could not load the rules">{err}</Banner> : <Skeleton h={220} />
  const set = <K extends keyof PolicyInput>(k: K, v: PolicyInput[K]) => { setSaved(false); setF({ ...f, [k]: v }) }
  async function save() {
    setBusy(true); setErr(null)
    try { const p = await putAttendancePolicy(siteId, f!); setMeta({ is_default: p.is_default, updated_by: p.updated_by }); setSaved(true) } catch (e) { setErr(e instanceof ApiError ? e.message : 'Could not save') } finally { setBusy(false) }
  }
  return (
    <section className="tp-card"><div className="tp-body tp-stack" style={{ maxWidth: 640 }}>
      {meta?.is_default ? <Banner tone="info" title="Using Tempo’s defaults">This site has no saved rules yet. These are the values in force; save to make them this site’s explicit policy.</Banner>
        : <Status tone="ok">Saved{meta?.updated_by ? ` by ${meta.updated_by}` : ''}</Status>}
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      <fieldset className="tp-stack" disabled={!canEdit} style={{ border: 0, padding: 0, margin: 0 }}>
        <label className="tp-field">Breaks
          <select value={f.breaks_paid ? 'paid' : 'unpaid'} onChange={(e) => set('breaks_paid', e.target.value === 'paid')}>
            <option value="unpaid">Unpaid — recorded break time is deducted from payable hours</option><option value="paid">Paid — breaks are recorded but not deducted</option></select></label>
        <div className="tp-cols2">
          <label className="tp-field">Round payable hours to
            <select value={f.rounding_minutes} onChange={(e) => set('rounding_minutes', Number(e.target.value))}>{[0, 1, 5, 6, 10, 15, 30].map((m) => <option key={m} value={m}>{m === 0 ? 'No rounding' : `${m} minutes`}</option>)}</select></label>
          <label className="tp-field">Rounding direction
            <select value={f.rounding_mode} disabled={f.rounding_minutes === 0} onChange={(e) => set('rounding_mode', e.target.value as PolicyInput['rounding_mode'])}>
              <option value="nearest">Nearest</option><option value="up">Always up</option><option value="down">Always down</option></select></label>
        </div>
        <div className="tp-cols2">
          <label className="tp-field">Repeat taps ignored for (seconds)<input type="number" min={5} max={300} value={f.duplicate_window_seconds} onChange={(e) => set('duplicate_window_seconds', Number(e.target.value))} /></label>
          <label className="tp-field">Late after (minutes past start)<input type="number" min={0} max={60} value={f.late_grace_minutes} onChange={(e) => set('late_grace_minutes', Number(e.target.value))} /></label>
        </div>
        <div className="tp-cols2">
          <label className="tp-field">Missing clock-out after (hours)<input type="number" min={4} max={48} value={f.missing_punch_after_hours} onChange={(e) => set('missing_punch_after_hours', Number(e.target.value))} /></label>
          <label className="tp-field">Flag long days from (hours)<input type="number" min={6} max={24} value={f.excessive_hours} onChange={(e) => set('excessive_hours', Number(e.target.value))} /></label>
        </div>
        <label className="tp-field">Location at each punch
          <select value={f.location_mode} disabled={!fenced && f.location_mode === 'off'} onChange={(e) => set('location_mode', e.target.value as PolicyInput['location_mode'])}>
            <option value="off">Off — location is not asked for</option>
            <option value="record">Record — store where the kiosk is; flag punches outside the fence, never block them</option>
            <option value="require">Require — refuse a punch from outside the fence or with no location</option></select></label>
        {!fenced && <p className="tp-muted" style={{ fontSize: 12 }}>Set the geofence below first; location checking needs it.</p>}
      </fieldset>
      <Fence siteId={siteId} canEdit={canEdit} onChange={onFence} />
      <p className="tp-muted" style={{ fontSize: 12 }}>Location describes the <b>kiosk’s position when the tap happened</b> (a kiosk is shared, so it says nothing about the worker beyond that). It is a point-in-time check, not tracking; kiosks tell workers when it is on. Rounding applies to payable hours only; the original punches are always kept. A missing clock-out is never closed automatically — a supervisor corrects it and a second person approves. Changing these rules affects hours calculated from now on, including timesheets not yet approved.</p>
      {canEdit ? <div className="tp-row"><button className="tp-btn primary" disabled={busy} onClick={() => void save()}>{busy ? 'Saving…' : 'Save rules'}</button>{saved && <Status tone="ok">Saved</Status>}</div>
        : <p className="tp-muted">Only a tenant administrator can change these rules.</p>}
    </div></section>
  )
}
