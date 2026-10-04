import { useCallback, useEffect, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { ApiError } from '../api/client'
import * as me from '../api/me'
import { Banner, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { fmtTime } from '../lib/format'
import { zonedToUtcIso } from '../lib/zoned'
import LoginPage from './Login'

/** A web companion to the Tempo employee app: the same information, from the same server rules, for team members who sign in on a computer.
 *  Not the app: no push notifications, no kiosk QR, no installation. */
const useLoad = <T,>(fn: () => Promise<T>, deps: unknown[] = []) => {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const reload = useCallback(() => { setErr(null); fn().then(setData).catch((e) => setErr(e instanceof ApiError ? e.message : 'Could not load.')) }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setData(null); reload() }, [reload])
  return { data, err, reload }
}
const hm = (m: number) => `${Math.floor(m / 60)} h${m % 60 ? ` ${Math.round(m % 60)} min` : ''}`
const dt = (iso: string, tz: string) => fmtTime(iso, tz, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
const tm = (iso: string, tz: string) => fmtTime(iso, tz, { hour: '2-digit', minute: '2-digit', hour12: false })
const Problem = ({ msg, retry }: { msg: string; retry: () => void }) => <Banner tone="bad" title="Could not load">{msg} <button className="tp-btn" onClick={retry}>Try again</button></Banner>

function Shifts({ tz }: { tz: string }) {
  const s = useLoad(me.meShifts)
  const c = useLoad(me.meChanges)
  useEffect(() => { if ((c.data?.unseen ?? 0) > 0) void me.meChangesSeen().catch(() => undefined) }, [c.data])
  const upcoming = (s.data?.shifts ?? []).filter((x) => new Date(x.end_at) > new Date())
  return (
    <>
      <PageHead title="My shifts" sub="Only published rosters appear here. A roster that is still a draft is not shown." />
      {s.err && <Problem msg={s.err} retry={s.reload} />}
      <section className="tp-card"><div className="tp-body">
        {!s.data ? <Skeleton h={120} /> : upcoming.length === 0 ? <Empty title="No upcoming shifts">When your manager publishes a roster that includes you, it shows here.</Empty> : (
          <table className="tp-table"><thead><tr><th>When</th><th>Role</th><th>Where</th><th>Length</th><th>Break</th><th>Instructions</th></tr></thead>
            <tbody>{upcoming.map((x) => (
              <tr key={x.id}><td>{dt(x.start_at, x.timezone)} – {tm(x.end_at, x.timezone)}{x.overnight && <div><Status tone="neutral">Overnight</Status></div>}{x.dst_change_during_shift && <div><Status tone="risk">Clocks change during this shift</Status></div>}{x.status === 'needs_reconfirmation' && <div><Status tone="risk">Please confirm the change in Offers</Status></div>}</td>
                <td>{x.role}<div className="tp-muted" style={{ fontSize: 12 }}>{x.zone}</div></td><td>{x.site_name}</td><td className="tp-num">{hm(x.duration_minutes)}</td><td>{x.break_minutes ? `${x.break_minutes} min unpaid` : <span className="tp-muted">not set</span>}</td><td>{x.instructions ?? <span className="tp-muted">none</span>}</td></tr>))}</tbody></table>)}
      </div></section>
      <section className="tp-card"><header><h2>Roster changes</h2>{(c.data?.unseen ?? 0) > 0 && <Status tone="risk">{c.data!.unseen} new</Status>}</header><div className="tp-body">
        {!c.data ? <Skeleton h={60} /> : c.data.changes.length === 0 ? <p className="tp-muted" style={{ margin: 0 }}>No changes to your roster in the last 30 days.</p> : (
          <ul className="tp-list" style={{ listStyle: 'none', padding: 0, margin: 0 }}>{c.data.changes.map((x) => { const w = x.after ?? x.before; return (
            <li key={x.id} className="tp-item" style={{ gridTemplateColumns: 'auto 1fr auto', cursor: 'default' }}><Status tone={x.kind === 'added' ? 'ok' : x.kind === 'cancelled' ? 'bad' : 'risk'}>{x.kind === 'added' ? 'New shift' : x.kind === 'changed' ? 'Changed' : 'Cancelled'}</Status>
              <span>{w?.start_at && w?.end_at ? `${dt(w.start_at, tz)} – ${tm(w.end_at, tz)}` : ''}{x.kind === 'changed' && x.before?.start_at ? <span className="tp-muted"> (was {dt(x.before.start_at, tz)})</span> : null}</span><span className="tp-muted" style={{ fontSize: 12 }}>{dt(x.at, tz)}</span></li>) })}</ul>)}
      </div></section>
    </>
  )
}

function Offers() {
  const o = useLoad(me.meOffers)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const answer = async (id: string, a: 'accept' | 'decline') => { setBusy(id); setErr(null); try { await me.meRespond(id, a); o.reload() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Could not send your answer.') } finally { setBusy(null) } }
  const LABEL: Record<string, string> = { open: 'Open to you', accepted: 'You accepted: waiting for your manager', declined: 'You declined', taken: 'Taken by someone else', expired: 'Expired', cancelled: 'Cancelled', needs_reconfirmation: 'Changed: please confirm again', not_taken: 'Not taken', rejected_by_manager: 'Your manager did not confirm' }
  return (
    <>
      <PageHead title="Shift offers" sub="Extra shifts your manager has offered you. Accepting holds the shift until your manager confirms it." />
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      {o.err && <Problem msg={o.err} retry={o.reload} />}
      {!o.data ? <Skeleton h={100} /> : o.data.offers.length === 0 ? <section className="tp-card"><div className="tp-body"><Empty title="No shift offers" /></div></section> : o.data.offers.map((x) => {
        const st = x.status_for_me ?? 'open'
        const live = ['open', 'accepted', 'needs_reconfirmation'].includes(st)
        return (
          <section key={x.id} className="tp-card"><div className="tp-body tp-stack">
            <div className="tp-row" style={{ justifyContent: 'space-between' }}><b>{dt(x.start_at, x.timezone)} – {tm(x.end_at, x.timezone)}</b><Status tone={st === 'open' ? 'neutral' : st === 'accepted' ? 'ok' : st === 'needs_reconfirmation' ? 'risk' : st === 'cancelled' || st === 'rejected_by_manager' ? 'bad' : 'neutral'}>{LABEL[st] ?? st}</Status></div>
            <div>{x.role} · {x.zone} · {x.site_name}{x.break_minutes ? ` · ${x.break_minutes} min break` : ''}</div>
            {x.instructions && <div className="tp-muted">{x.instructions}</div>}
            {x.expires_at && <div className="tp-muted" style={{ fontSize: 12 }}>Answer by {dt(x.expires_at, x.timezone)}</div>}
            {live && <div className="tp-row">{st !== 'accepted' && <button className="tp-btn primary" disabled={busy === x.id} onClick={() => void answer(x.id, 'accept')}>{st === 'needs_reconfirmation' ? 'Confirm the change' : 'Accept this shift'}</button>}<button className="tp-btn" disabled={busy === x.id} onClick={() => void answer(x.id, 'decline')}>{st === 'accepted' ? 'Withdraw' : 'Decline'}</button></div>}
          </div></section>)
      })}
    </>
  )
}

const LEAVE_KIND: Record<string, string> = { annual: 'Annual leave', personal: 'Personal / sick', unpaid: 'Unpaid', other: 'Other' }
function Requests({ tz }: { tz: string }) {
  const l = useLoad(me.meLeave)
  const a = useLoad(me.meAvailability)
  const [kind, setKind] = useState('annual')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [reason, setReason] = useState('')
  const [af, setAf] = useState('')
  const [at, setAt] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<unknown>, done: string, after: () => void) => { setBusy(true); setErr(null); setOk(null); try { await fn(); setOk(done); after() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Could not save.') } finally { setBusy(false) } }
  return (
    <>
      <PageHead title="Leave & availability" sub="Ask for leave (your manager decides) and mark times you cannot work (this takes effect straight away)." />
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      {ok && <Banner tone="info" title="Done">{ok}</Banner>}
      <section className="tp-card"><header><h2>My leave requests</h2></header><div className="tp-body">
        {l.err && <Problem msg={l.err} retry={l.reload} />}
        {!l.data ? <Skeleton h={80} /> : l.data.requests.length === 0 ? <p className="tp-muted" style={{ margin: 0 }}>No leave requests.</p> : (
          <table className="tp-table"><thead><tr><th>Days</th><th>Kind</th><th>Status</th><th /></tr></thead><tbody>{l.data.requests.map((r) => (
            <tr key={r.id}><td>{r.start_date} → {r.end_date}</td><td>{LEAVE_KIND[r.kind]}</td><td><Status tone={r.status === 'approved' ? 'ok' : r.status === 'pending' ? 'risk' : r.status === 'rejected' ? 'bad' : 'neutral'}>{r.status === 'pending' ? 'Waiting for your manager' : r.status === 'approved' ? 'Approved' : r.status === 'rejected' ? 'Declined' : 'Cancelled'}</Status>{r.decision_note && <div className="tp-muted" style={{ fontSize: 12 }}>Manager: {r.decision_note}</div>}</td>
              <td>{(r.status === 'pending' || r.status === 'approved') && <button className="tp-btn" disabled={busy} onClick={() => void run(() => me.meCancelLeave(r.id), 'Leave cancelled.', l.reload)}>Cancel</button>}</td></tr>))}</tbody></table>)}
        <form className="tp-stack" style={{ marginTop: 12, maxWidth: 520 }} onSubmit={(e) => { e.preventDefault(); void run(() => me.meRequestLeave({ kind, start_date: from, end_date: to || from, reason: reason || undefined }), 'Request sent. You will be notified of the decision.', () => { setFrom(''); setTo(''); setReason(''); l.reload() }) }}>
          <h3 style={{ margin: 0, fontSize: 14 }}>Ask for leave</h3>
          <label className="tp-field">Kind<select value={kind} onChange={(e) => setKind(e.target.value)}>{Object.entries(LEAVE_KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
          <div className="tp-cols2"><label className="tp-field">First day<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} required /></label><label className="tp-field">Last day<input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></label></div>
          <label className="tp-field">Reason (optional)<input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} /></label>
          <button className="tp-btn primary" disabled={busy || !from}>Send request</button>
        </form>
      </div></section>
      <section className="tp-card"><header><h2>Times I cannot work</h2></header><div className="tp-body">
        {a.err && <Problem msg={a.err} retry={a.reload} />}
        {!a.data ? <Skeleton h={60} /> : a.data.entries.length === 0 ? <p className="tp-muted" style={{ margin: 0 }}>Nothing marked.</p> : (
          <table className="tp-table"><tbody>{a.data.entries.map((x) => <tr key={x.id}><td>{dt(x.start_at, tz)} → {dt(x.end_at, tz)}</td><td><Status tone={x.status === 'leave' ? 'ok' : 'neutral'}>{x.status === 'leave' ? 'Leave' : x.source === 'tempo_employee' ? 'From you' : 'Set by your manager'}</Status></td><td>{x.editable && <button className="tp-btn" disabled={busy} onClick={() => void run(() => me.meRemoveAvailability(x.id), 'Removed.', a.reload)}>Remove</button>}</td></tr>)}</tbody></table>)}
        <form className="tp-stack" style={{ marginTop: 12, maxWidth: 520 }} onSubmit={(e) => { e.preventDefault(); void run(() => me.meAddAvailability(zonedToUtcIso(af, tz), zonedToUtcIso(at, tz)), 'Saved. Your manager will not roster you for this time.', () => { setAf(''); setAt(''); a.reload() }) }}>
          <h3 style={{ margin: 0, fontSize: 14 }}>Mark time I cannot work ({tz})</h3>
          <div className="tp-cols2"><label className="tp-field">From<input type="datetime-local" value={af} onChange={(e) => setAf(e.target.value)} required /></label><label className="tp-field">Until<input type="datetime-local" value={at} min={af} onChange={(e) => setAt(e.target.value)} required /></label></div>
          <button className="tp-btn primary" disabled={busy || !af || !at}>Save</button>
        </form>
      </div></section>
    </>
  )
}

function Clockings({ tz }: { tz: string }) {
  const r = useLoad(me.meAttendance)
  const KIND: Record<string, string> = { clock_in: 'Clocked in', break_start: 'Break started', break_end: 'Break ended', clock_out: 'Clocked out' }
  return (
    <>
      <PageHead title="My clockings" sub="What Tempo recorded. You clock in and out at the kiosk on site." />
      {r.err && <Problem msg={r.err} retry={r.reload} />}
      {r.data && <Status tone={r.data.current_state === 'working' ? 'ok' : r.data.current_state === 'on_break' ? 'risk' : 'neutral'}>{r.data.current_state === 'working' ? 'Clocked in now' : r.data.current_state === 'on_break' ? 'On a break' : 'Not clocked in'}</Status>}
      <section className="tp-card"><div className="tp-body">
        {!r.data ? <Skeleton h={100} /> : r.data.sessions.length === 0 ? <Empty title="No clockings in the last 30 days" /> : (
          <table className="tp-table"><thead><tr><th>Day</th><th>Clockings</th><th>Worked</th><th>Break</th><th>Payable</th><th>Approval</th></tr></thead><tbody>{r.data.sessions.map((s) => (
            <tr key={s.id}><td>{dt(s.started_at, tz)}</td><td>{s.punches.map((p, i) => <div key={i} style={{ fontSize: 13 }}>{tm(p.at, tz)} {KIND[p.kind] ?? p.kind}{p.source === 'correction' ? ' (added by your manager)' : ''}</div>)}</td><td className="tp-num">{hm(s.worked_minutes)}</td><td className="tp-num">{hm(s.break_minutes)}</td>
              <td className="tp-num">{s.payable_minutes != null ? hm(s.payable_minutes) : <span className="tp-muted" title="Shown once your manager approves the timesheet">when approved</span>}</td><td>{s.approval === 'approved' ? <Status tone="ok">Approved</Status> : <Status tone="risk">Awaiting approval</Status>}{s.corrected && <div className="tp-muted" style={{ fontSize: 12 }}>corrected</div>}</td></tr>))}</tbody></table>)}
      </div></section>
    </>
  )
}

function Settings() {
  const p = useLoad(me.mePrefs)
  const [f, setF] = useState<me.MePrefs | null>(null)
  const [msg, setMsg] = useState<{ tone: 'info' | 'bad'; text: string } | null>(null)
  useEffect(() => { if (p.data) setF(p.data) }, [p.data])
  if (!f) return p.err ? <Problem msg={p.err} retry={p.reload} /> : <Skeleton h={200} />
  const save = async (patch: Partial<me.MePrefs>) => { const n = { ...f, ...patch }; setF(n); setMsg(null); try { const { lead_choices: _l, sms_available: _s, ...rest } = n; void _l; void _s; setF(await me.mePutPrefs(rest)); setMsg({ tone: 'info', text: 'Saved.' }) } catch (e) { setF(p.data); setMsg({ tone: 'bad', text: e instanceof ApiError ? e.message : 'Could not save.' }) } }
  const cats: [keyof me.MePrefs, string, string][] = [['roster_published', 'Roster published', 'When your roster for a week is published.'], ['shift_changes', 'Shift changes and cancellations', 'When one of your shifts moves or is cancelled.'], ['offers', 'Shift offers', 'When you are offered a shift.'], ['reminders', 'Shift reminders', 'A reminder before each shift.'], ['decisions', 'Request decisions', 'When leave and similar requests are decided.']]
  return (
    <>
      <PageHead title="Notification settings" sub="These settings apply to the Tempo phone app, which sends the notifications. This website shows everything without notifications." />
      {msg && <Banner tone={msg.tone} title={msg.tone === 'info' ? 'Done' : 'Problem'}>{msg.text}</Banner>}
      <section className="tp-card"><div className="tp-body tp-stack" style={{ maxWidth: 560 }}>
        <label className="tp-row"><input type="checkbox" checked={f.push_enabled} onChange={(e) => void save({ push_enabled: e.target.checked })} /> Send push notifications to my phone</label>
        {cats.map(([k, l, h]) => <label key={k} className="tp-row"><input type="checkbox" checked={f[k] as boolean} disabled={!f.push_enabled} onChange={(e) => void save({ [k]: e.target.checked } as Partial<me.MePrefs>)} /> <span>{l}<span className="tp-muted" style={{ fontSize: 12, display: 'block' }}>{h}</span></span></label>)}
        <label className="tp-field" style={{ maxWidth: 260 }}>Remind me before a shift<select value={f.reminder_lead_minutes} onChange={(e) => void save({ reminder_lead_minutes: Number(e.target.value) })}>{f.lead_choices.map((m) => <option key={m} value={m}>{m >= 60 ? `${m / 60} hour${m === 60 ? '' : 's'}` : `${m} minutes`} before</option>)}</select></label>
        <p className="tp-muted" style={{ fontSize: 12, margin: 0 }}>Lock-screen messages never show times, places or names.</p>
      </div></section>
    </>
  )
}

export default function MyTempo() {
  const { status, access, signOut } = useTempoContext()
  const prof = useLoad(me.meProfile)
  if (status === 'loading') return <div className="tp-app" style={{ padding: 32 }}><Skeleton h={28} w={240} /></div>
  if (status !== 'authenticated' || !access) return <LoginPage />
  if (!access.permissions.includes('labour.self')) {
    if (access.platform_admin && !access.tenant_id) return <Navigate to="/platform" replace />
    if (access.permissions.includes('labour.read')) return <Navigate to="/" replace />   // a manager who lands here goes to the manager screens
  }
  if (!access.permissions.includes('labour.self')) return <div className="tp-app" style={{ padding: 32, maxWidth: 560 }}><Banner tone="info" title="This page is for team members">Managers use the main Tempo screens. <NavLink to="/">Go there</NavLink></Banner></div>
  const tz = prof.data?.site.timezone ?? 'UTC'
  const tabs: [string, string, boolean?][] = [['/my', 'Shifts', true], ['/my/offers', 'Offers'], ['/my/requests', 'Leave & availability'], ['/my/clockings', 'Clockings'], ['/my/settings', 'Notifications']]
  return (
    <div className="tp-app">
      <header className="tp-topbar"><div className="tp-brand"><img src="/brand/tempo-lockup-dark.png" alt="Tempo" /></div><div className="tp-spacer" />
        <div className="tp-user"><div><div>{prof.data?.display_name ?? 'Team member'}</div><small>{prof.data ? `${prof.data.company} · ${prof.data.site.name}` : ''}</small></div><button className="tp-iconbtn" onClick={() => void signOut()}>Sign out</button></div></header>
      <div style={{ maxWidth: 1000, margin: '0 auto', padding: 16 }}>
        <Banner tone="info" title="Tempo on the web for team members">You are looking at your own roster, requests and clockings. The Tempo phone app shows the same information and also sends notifications.</Banner>
        <nav aria-label="My Tempo" className="tp-row" style={{ margin: '12px 0', flexWrap: 'wrap' }}>{tabs.map(([to, l, end]) => <NavLink key={to} to={to} end={!!end} className="tp-btn" style={{ textDecoration: 'none' }}>{l}</NavLink>)}</nav>
        <main id="main" tabIndex={-1} className="tp-stack">
          <Routes><Route index element={<Shifts tz={tz} />} /><Route path="offers" element={<Offers />} /><Route path="requests" element={<Requests tz={tz} />} /><Route path="clockings" element={<Clockings tz={tz} />} /><Route path="settings" element={<Settings />} /><Route path="*" element={<Navigate to="/my" replace />} /></Routes>
        </main>
      </div>
    </div>
  )
}
