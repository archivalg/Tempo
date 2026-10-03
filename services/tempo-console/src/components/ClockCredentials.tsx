import { useCallback, useEffect, useState } from 'react'
import { addSkill, getAppAccess, getClockCredentials, inviteToApp, patchWorker, removeSkill, setClockPin, unlinkFromApp, unlockClockCredential, type AppAccess, type ClockCredential } from '../api/ops'
import { ApiError } from '../api/client'
import { Banner, Drawer, Empty, Skeleton, Status } from './ui'

/** The site's people for the kiosk and rosters: badge number, active status, PIN and skills. PINs are set, never shown; a reset also clears a lockout. */
export function ClockCredentials({ siteId }: { siteId: string }) {
  const [rows, setRows] = useState<ClockCredential[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [editing, setEditing] = useState<{ id: string; field: 'pin' | 'badge' } | null>(null)
  const [val, setVal] = useState('')
  const [skillsFor, setSkillsFor] = useState<string | null>(null)
  const [newSkill, setNewSkill] = useState('')
  const [busy, setBusy] = useState(false)
  const [access, setAccess] = useState<AppAccess | null>(null)
  const [invite, setInvite] = useState<{ label: string; link: string; app: string } | null>(null)
  const load = useCallback(() => { getClockCredentials(siteId).then(setRows).catch((e) => setErr(e.message)); getAppAccess(siteId).then(setAccess).catch(() => undefined) }, [siteId])
  useEffect(() => { setRows(null); load() }, [load])
  async function act(fn: () => Promise<unknown>, keepOpen = false) {
    setBusy(true); setErr(null)
    try { await fn(); if (!keepOpen) { setEditing(null); setVal('') } load() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Failed') } finally { setBusy(false) }
  }
  const person = rows?.find((r) => r.worker_id === skillsFor)
  return (
    <section className="tp-card">
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      {!rows ? <div className="tp-body"><Skeleton h={160} /></div> : rows.length === 0 ? <Empty title="No workers at this site">Import staff on the Data page first.</Empty> : (
        <div style={{ overflow: 'auto', maxHeight: 560 }}>
          <table className="tp-table">
            <thead><tr><th>Worker</th><th>Badge no.</th><th>Status</th><th>PIN</th><th>Skills</th><th>Tempo app</th><th /></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.worker_id}>
                <td>{r.label}</td>
                <td className="tp-num">{editing?.id === r.worker_id && editing.field === 'badge' ? (
                  <form className="tp-row" onSubmit={(e) => { e.preventDefault(); void act(() => patchWorker(r.worker_id, { badge_no: val })) }}>
                    <input aria-label={`New badge number for ${r.label}`} inputMode="numeric" value={val} onChange={(e) => setVal(e.target.value.replace(/\D/g, '').slice(0, 24))} style={{ width: 100 }} />
                    <button className="tp-btn primary" disabled={busy || !val}>Save</button><button type="button" className="tp-btn" onClick={() => setEditing(null)}>Cancel</button></form>
                ) : <span className="tp-row">{r.badge_no ?? <span className="tp-muted">none</span>}<button className="tp-btn" onClick={() => { setEditing({ id: r.worker_id, field: 'badge' }); setVal(r.badge_no ?? '') }}>{r.badge_no ? 'Change' : 'Set'}</button></span>}</td>
                <td>{r.status === 'active' ? <Status tone="ok">Active</Status> : <Status tone="neutral">{r.status}</Status>}</td>
                <td>{r.locked ? <Status tone="bad">Locked</Status> : r.has_pin ? <Status tone="ok">Set</Status> : <Status tone="risk">Not set</Status>}</td>
                <td>{r.skills.length ? r.skills.join(', ') : <span className="tp-muted">none</span>} <button className="tp-btn" onClick={() => { setSkillsFor(r.worker_id); setNewSkill('') }} aria-label={`Edit skills for ${r.label}`}>Edit</button></td>
                <td>{(() => { const a = access?.workers[r.worker_id]; if (!a) return <span className="tp-muted">…</span>
                  return <span className="tp-row">{a.state === 'active' ? <Status tone="ok">Joined{a.push_devices ? ` · ${a.push_devices} phone${a.push_devices === 1 ? '' : 's'}` : ''}</Status> : a.state === 'invited' ? <Status tone="risk">Invited</Status> : <Status tone="neutral">Not invited</Status>}
                    {r.status === 'active' && <button className="tp-btn" disabled={busy} onClick={() => void act(async () => { const x = await inviteToApp(r.worker_id); setInvite({ label: r.label, link: `${window.location.origin}${x.invite_path}`, app: x.app_link }) }, true)}>{a.state === 'not_invited' ? 'Invite' : 'New link'}</button>}
                    {a.state !== 'not_invited' && <button className="tp-btn danger" disabled={busy} onClick={() => { if (window.confirm(`Remove ${r.label}'s access to the Tempo app? Their phone is signed out immediately.`)) void act(() => unlinkFromApp(r.worker_id), true) }}>Remove</button>}</span> })()}</td>
                <td>{editing?.id === r.worker_id && editing.field === 'pin' ? (
                  <form className="tp-row" onSubmit={(e) => { e.preventDefault(); void act(() => setClockPin(r.worker_id, val)) }}>
                    <input aria-label={`New PIN for ${r.label}`} inputMode="numeric" autoComplete="off" pattern="[0-9]{4,8}" placeholder="4–8 digits" value={val} onChange={(e) => setVal(e.target.value.replace(/\D/g, '').slice(0, 8))} style={{ width: 110 }} />
                    <button className="tp-btn primary" disabled={busy || val.length < 4}>Save</button><button type="button" className="tp-btn" onClick={() => { setEditing(null); setVal('') }}>Cancel</button>
                  </form>
                ) : (
                  <span className="tp-row"><button className="tp-btn" onClick={() => { setEditing({ id: r.worker_id, field: 'pin' }); setVal('') }}>{r.has_pin ? 'Reset PIN' : 'Set PIN'}</button>
                    {r.locked && <button className="tp-btn" disabled={busy} onClick={() => void act(() => unlockClockCredential(r.worker_id))}>Unlock</button>}
                    {r.status === 'active' ? <button className="tp-btn danger" disabled={busy} onClick={() => { if (window.confirm(`Make ${r.label} inactive? They will no longer be able to clock in or be rostered.`)) void act(() => patchWorker(r.worker_id, { status: 'inactive' })) }}>Make inactive</button>
                      : <button className="tp-btn" disabled={busy} onClick={() => void act(() => patchWorker(r.worker_id, { status: 'active' }))}>Reactivate</button>}</span>)}</td>
              </tr>))}</tbody>
          </table>
        </div>)}
      <p className="tp-muted tp-body" style={{ fontSize: 12 }}>Workers clock in with their badge number and PIN. Badge numbers must be unique. After repeated wrong PINs the credential locks for a short time; setting a new PIN or unlocking clears it. Making someone inactive keeps their history; they cannot be made inactive while clocked in, and any future shifts they hold will show as conflicts until reassigned.</p>
      {invite && (
        <Drawer title={`App invitation — ${invite.label}`} onClose={() => setInvite(null)}>
          <div className="tp-stack"><Banner tone="info" title="Shown once">Give this to the employee privately. It works once and expires; they choose their own username and password. Tempo does not email it.</Banner>
            <label className="tp-field">Link to open on their phone<input readOnly value={invite.app} onFocus={(e) => e.currentTarget.select()} /></label>
            <label className="tp-field">Web link (works in any browser, then open the app)<input readOnly value={invite.link} onFocus={(e) => e.currentTarget.select()} /></label>
            <button className="tp-btn" onClick={() => void navigator.clipboard?.writeText(invite.app)}>Copy phone link</button></div>
        </Drawer>)}
      {person && (
        <Drawer title={`Skills — ${person.label}`} onClose={() => setSkillsFor(null)}>
          <div className="tp-stack">
            <p className="tp-muted">Skills decide which roles a person can be rostered to. Removing one does not change rosters already published; new drafts and checks stop counting it.</p>
            {person.skills.length === 0 ? <Empty title="No skills recorded" /> : <ul className="tp-list" style={{ listStyle: 'none', padding: 0, margin: 0 }}>{person.skills.map((k) => (
              <li key={k} className="tp-item" style={{ gridTemplateColumns: '1fr auto', cursor: 'default' }}><span className="t">{k}</span><button className="tp-btn" disabled={busy} aria-label={`Remove ${k}`} onClick={() => void act(() => removeSkill(person.worker_id, k), true)}>Remove</button></li>))}</ul>}
            <form className="tp-row" onSubmit={(e) => { e.preventDefault(); void act(async () => { await addSkill(person.worker_id, newSkill.trim()); setNewSkill('') }, true) }}>
              <label className="tp-field" style={{ flex: 1 }}>Add a skill<input value={newSkill} onChange={(e) => setNewSkill(e.target.value)} placeholder="forklift" /></label>
              <button className="tp-btn primary" disabled={busy || !newSkill.trim()}>Add</button>
            </form>
          </div>
        </Drawer>)}
    </section>
  )
}
