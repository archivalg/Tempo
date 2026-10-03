import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { getDeliveries, getMessaging, putMessaging, runJobsNow, type Deliveries, type Messaging } from '../api/ops'
import { HelpLink } from './HelpLink'
import { Banner, Skeleton, Status } from './ui'

/** Company-wide settings for notifications to the Tempo app, plus what was attempted, what the provider said, and what phones acknowledged. */
export function MessagingSettings() {
  const [m, setM] = useState<Messaging | null>(null)
  const [d, setD] = useState<Deliveries | null>(null)
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const load = () => { getMessaging().then(setM).catch((e) => setMsg({ tone: 'bad', text: e.message })); getDeliveries().then(setD).catch(() => undefined) }
  useEffect(load, [])
  if (!m) return msg ? <Banner tone="bad" title="Could not load notification settings">{msg.text}</Banner> : <Skeleton h={120} />
  const save = async (patch: Partial<Messaging>) => {
    setBusy(true); setMsg(null)
    try { setM(await putMessaging({ push_enabled: m.push_enabled, sms_enabled: m.sms_enabled, sms_monthly_cap: m.sms_monthly_cap, default_reminder_lead_minutes: m.default_reminder_lead_minutes, ...patch })); setMsg({ tone: 'ok', text: 'Saved.' }) } catch (e) { setMsg({ tone: 'bad', text: e instanceof ApiError ? e.message : 'Could not save' }) } finally { setBusy(false) }
  }
  const total = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0)
  return (
    <section className="tp-card" aria-label="Mobile notifications"><header><h2>Mobile notifications</h2><HelpLink id="mobile-notifications" /></header>
      <div className="tp-body tp-stack">
        {msg && <Banner tone={msg.tone === 'ok' ? 'info' : 'bad'} title={msg.tone === 'ok' ? 'Done' : 'Problem'}>{msg.text}</Banner>}
        <dl className="tp-dl"><dt>Push provider</dt><dd>{m.push_provider === 'disabled' ? <Status tone="risk">Not configured: nothing is sent</Status> : <Status tone="ok">{m.push_provider}</Status>}</dd>
          <dt>Text messages</dt><dd>{m.sms_provider === 'disabled' ? <Status tone="neutral">No provider connected</Status> : <Status tone="ok">{m.sms_provider}</Status>}</dd></dl>
        <label className="tp-row"><input type="checkbox" checked={m.push_enabled} disabled={busy} onChange={(e) => void save({ push_enabled: e.target.checked })} /> Send push notifications to employees’ phones</label>
        <label className="tp-field" style={{ maxWidth: 320 }}>Default reminder before a shift
          <select value={m.default_reminder_lead_minutes} disabled={busy} onChange={(e) => void save({ default_reminder_lead_minutes: Number(e.target.value) })}>{m.lead_choices.map((x) => <option key={x} value={x}>{x >= 60 ? `${x / 60} hour${x === 60 ? '' : 's'}` : `${x} minutes`}</option>)}</select></label>
        <fieldset className="tp-stack" style={{ border: 0, padding: 0 }}><legend style={{ fontWeight: 600 }}>Text messages (urgent changes only)</legend>
          <label className="tp-row"><input type="checkbox" checked={m.sms_enabled} disabled={busy} onChange={(e) => void save({ sms_enabled: e.target.checked })} /> Allow text messages for urgent shift changes</label>
          <label className="tp-field" style={{ maxWidth: 220 }}>Monthly limit (messages)<input type="number" min={0} value={m.sms_monthly_cap} disabled={busy || !m.sms_enabled} onChange={(e) => setM({ ...m, sms_monthly_cap: Number(e.target.value) })} onBlur={() => void save({ sms_monthly_cap: m.sms_monthly_cap })} /></label>
          <p className="tp-muted" style={{ fontSize: 12, margin: 0 }}>{m.sms_sent_this_month} sent this month. {m.notes[0]}</p></fieldset>
        {d && (
          <div className="tp-stack"><h3 style={{ margin: '8px 0 0', fontSize: 14 }}>Last {d.window_days} days</h3>
            <table className="tp-table"><tbody>
              <tr><td>Notification jobs</td><td>{Object.entries(d.jobs).map(([k, v]) => `${v} ${k}`).join(', ') || '—'}</td></tr>
              <tr><td>Accepted by the push provider</td><td>{d.deliveries.accepted ?? 0} of {total(d.deliveries)} attempts <span className="tp-muted">(not proof it reached a phone)</span></td></tr>
              <tr><td>Provider says handed to Apple/Google</td><td>{d.provider_receipts_ok}</td></tr>
              <tr><td>Acknowledged by the employee’s phone</td><td>{d.acknowledged_by_device}</td></tr>
              <tr><td>Phones that could no longer be reached</td><td>{d.deliveries.device_unregistered ?? 0}</td></tr></tbody></table>
            <button className="tp-btn" style={{ width: 'fit-content' }} disabled={busy} onClick={() => { setBusy(true); runJobsNow().then((r) => setMsg({ tone: 'ok', text: `Processed ${r.processed} job(s), scheduled ${r.scheduled} reminder(s).` })).catch((e) => setMsg({ tone: 'bad', text: e.message })).finally(() => { setBusy(false); load() }) }}>Run due notifications now</button></div>)}
      </div>
    </section>
  )
}
