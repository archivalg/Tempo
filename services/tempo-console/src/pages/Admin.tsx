import { useState } from 'react'
import { apiRequest } from '../api/client'
import { Banner, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useSite } from '../components/AppShell'
import { fmtTime } from '../lib/format'
import { inviteUser, listUsers, userAction } from '../api/session'
import { useTempoContext } from '../context/TempoContextProvider'

interface Device { device_id: string; name: string | null; site_ids: string[]; status: string; enrolled_at: string | null; last_seen_at: string | null; enrolment_code: string | null }

export default function AdminPage() {
  const { site, sites } = useSite()
  const [nonce, setNonce] = useState(0)
  const [name, setName] = useState('')
  const [code, setCode] = useState<{ device: string; code: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const q = useApi(() => apiRequest<Device[]>('/devices'), [nonce])
  async function create() {
    setErr(null)
    try {
      const d = await apiRequest<Device>('/devices', { method: 'POST', body: { name, site_ids: [site!.site_id] } })
      setCode({ device: d.name ?? d.device_id, code: d.enrolment_code! }); setName(''); setNonce((n) => n + 1)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Could not create the device') }
  }
  async function disable(id: string) { await apiRequest(`/devices/${id}/disable`, { method: 'POST' }); setNonce((n) => n + 1) }
  return (
    <>
      <PageHead title="Administration" sub="Kiosk devices for the selected site" />
      {err && <Banner tone="bad" title="Error">{err}</Banner>}
      {code && <Banner tone="warn" title={`Enrolment code for ${code.device} — shown once`}><code style={{ fontSize: 15 }}>{code.code}</code><div>Enter it on the kiosk at /kiosk within 15 minutes. It cannot be shown again.</div></Banner>}
      <section className="tp-card"><header><h2>Kiosk devices</h2></header>
        <div className="tp-body tp-row">
          <label className="tp-field">Device name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Dock 2 kiosk" /></label>
          <button className="tp-btn primary" disabled={!name.trim() || !site} onClick={() => void create()}>Create &amp; get enrolment code</button>
          <span className="tp-muted">Binds to {site?.name}. You can only bind sites inside your own grants ({sites.length}).</span>
        </div>
        {!q.data ? <div className="tp-body"><Skeleton h={80} /></div> : q.data.length === 0 ? <Empty title="No devices yet" /> : (
          <table className="tp-table"><thead><tr><th>Name</th><th>Sites</th><th>Status</th><th>Last seen</th><th /></tr></thead><tbody>
            {q.data.map((d) => (<tr key={d.device_id}><td>{d.name}</td><td>{d.site_ids.join(', ')}</td><td><Status tone={d.status === 'active' ? 'ok' : d.status === 'pending' ? 'risk' : 'bad'}>{d.status}</Status></td><td>{d.last_seen_at ? fmtTime(d.last_seen_at, site?.timezone ?? 'UTC', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}</td><td>{d.status !== 'disabled' && <button className="tp-btn danger" onClick={() => void disable(d.device_id)}>Disable</button>}</td></tr>))}
          </tbody></table>
        )}
      </section>
      <UsersSection />
      <p className="tp-muted">Branding, policies and service credentials arrive with the rest of the tenant-admin module.</p>
    </>
  )
}

const ROLES = [['tenant_admin', 'Tenant admin'], ['operations_manager', 'Operations manager'], ['planner', 'Planner'], ['supervisor', 'Supervisor'], ['analyst', 'Analyst'], ['executive', 'Executive'], ['finance', 'Finance'], ['hr_authorised', 'HR (worker data)']] as const

function UsersSection() {
  const { access } = useTempoContext()
  const { sites } = useSite()
  const [nonce, setNonce] = useState(0)
  const q = useApi(() => listUsers(), [nonce])
  const [email, setEmail] = useState('')
  const [roles, setRoles] = useState<string[]>(['planner'])
  const [siteIds, setSiteIds] = useState<string[]>([])
  const [invite, setInvite] = useState<{ who: string; path: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const toggle = (arr: string[], v: string) => (arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v])
  async function create() {
    setErr(null)
    try {
      const u = await inviteUser({ email, roles, site_ids: siteIds.length ? siteIds : sites.map((s) => s.site_id).slice(0, 1), customer_ids: [] })
      setInvite(u.invite_path ? { who: u.email, path: `${window.location.origin}${u.invite_path}` } : null); setEmail(''); setNonce((n) => n + 1)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Could not invite') }
  }
  async function act(id: string, a: Parameters<typeof userAction>[1]) {
    setErr(null)
    try { const u = await userAction(id, a); if (u.invite_path) setInvite({ who: u.email, path: `${window.location.origin}${u.invite_path}` }); setNonce((n) => n + 1) } catch (e) { setErr(e instanceof Error ? e.message : 'Failed') }
  }
  return (
    <section className="tp-card" style={{ marginTop: 16 }}>
      <header><h2>Users</h2><span className="tp-muted" style={{ fontSize: 12 }}>invite-only · you can only grant sites and roles inside your own access</span></header>
      {err && <div className="tp-body"><Banner tone="bad" title="Error">{err}</Banner></div>}
      {invite && <div className="tp-body"><Banner tone="warn" title={`One-time link for ${invite.who} — shown once`}><code style={{ wordBreak: 'break-all' }}>{invite.path}</code><div>Send it privately. It expires and works once; it lets them choose their own password.</div></Banner></div>}
      <form className="tp-body tp-stack" onSubmit={(e) => { e.preventDefault(); void create() }}>
        <div className="tp-row">
          <label className="tp-field" style={{ minWidth: 260 }}>Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com" /></label>
          <fieldset className="tp-field" style={{ border: 0, padding: 0 }}><legend>Roles</legend><div className="tp-row">{ROLES.map(([v, l]) => <label key={v}><input type="checkbox" checked={roles.includes(v)} onChange={() => setRoles(toggle(roles, v))} /> {l}</label>)}</div></fieldset>
          <fieldset className="tp-field" style={{ border: 0, padding: 0 }}><legend>Sites</legend><div className="tp-row">{sites.map((s) => <label key={s.site_id}><input type="checkbox" checked={siteIds.includes(s.site_id)} onChange={() => setSiteIds(toggle(siteIds, s.site_id))} /> {s.name}</label>)}</div></fieldset>
          <button className="tp-btn primary" disabled={!email.includes('@') || !roles.length}>Invite</button>
        </div>
      </form>
      {!q.data ? <div className="tp-body"><Skeleton h={80} /></div> : (
        <table className="tp-table"><thead><tr><th>Person</th><th>Roles</th><th>Sites</th><th>Sign-in</th><th /></tr></thead><tbody>
          {q.data.map((u) => (
            <tr key={u.user_id}><td><b>{u.display_name ?? u.email}</b><div className="tp-muted" style={{ fontSize: 12 }}>{u.email}{u.is_self ? ' · you' : ''}</div></td>
              <td>{u.roles.map((r) => r.replace(/_/g, ' ')).join(', ')}</td><td>{u.site_ids.join(', ')}</td>
              <td>{u.membership !== 'active' ? <Status tone="bad">Suspended</Status> : !u.has_password ? <Status tone="risk">Invited</Status> : u.locked ? <Status tone="bad">Locked</Status> : <Status tone="ok">Active</Status>}{u.mfa_enabled && <span className="tp-muted"> · 2-step</span>}</td>
              <td>{!u.is_self && <div className="tp-row">
                {u.locked && <button className="tp-btn" onClick={() => void act(u.user_id, 'unlock')}>Unlock</button>}
                <button className="tp-btn" onClick={() => void act(u.user_id, 'reset-password')}>Reset password</button>
                {u.mfa_enabled && <button className="tp-btn" onClick={() => void act(u.user_id, 'reset-mfa')}>Reset 2-step</button>}
                {u.membership === 'active' ? <button className="tp-btn danger" onClick={() => void act(u.user_id, 'suspend')}>Suspend</button> : <button className="tp-btn" onClick={() => void act(u.user_id, 'reinstate')}>Reinstate</button>}
              </div>}</td></tr>))}
        </tbody></table>
      )}
      <span className="tp-sr-only">{access?.user_id}</span>
    </section>
  )
}
