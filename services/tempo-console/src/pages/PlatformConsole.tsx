import { useCallback, useEffect, useState } from 'react'
import { NavLink, Route, Routes } from 'react-router-dom'
import {
  addPlatformAdmin, approvePlan, createGrant, createTenant, endGrant, listGrants, listPlans, newPlanVersion, platformAudit, setSubscription, setTenantStatus, subscriptionHistory, tenantOverview,
  type AuditRow, type PlanDef, type SubscriptionInput, type SupportGrant, type TenantRow,
} from '../api/platform'
import { ApiError } from '../api/client'
import { Banner, Drawer, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import AccountPage from './Account'
import LoginPage from './Login'
import { fmtTime } from '../lib/format'

const when = (iso: string | null) => (iso ? fmtTime(iso, 'Australia/Melbourne', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : '—')
const msg = (e: unknown) => (e instanceof ApiError ? (e.message.includes('step-up') ? 'Your two-step verification is more than 30 minutes old. Sign out and sign in again, then retry.' : e.message) : 'Failed')

function useLoad<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const reload = useCallback(() => { setErr(null); fn().then(setData).catch((e) => setErr(msg(e))) }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setData(null); reload() }, [reload])
  return { data, err, reload }
}

function Tenants() {
  const [q, setQ] = useState('')
  const { data, err, reload } = useLoad(() => tenantOverview(q), [q])
  const [open, setOpen] = useState<TenantRow | 'new' | null>(null)
  const [plans, setPlans] = useState<PlanDef[]>([])
  useEffect(() => { listPlans().then(setPlans).catch(() => undefined) }, [])
  return (
    <>
      <PageHead title="Tenants" sub="Organisations, plans and allowances. Counts only: no customer business data is shown here.">
        <button className="tp-btn primary" onClick={() => setOpen('new')}>Create tenant</button>
      </PageHead>
      <div className="tp-row" style={{ marginBottom: 12 }}><input aria-label="Search tenants" placeholder="Search by name or ID" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 260 }} /></div>
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      <section className="tp-card">
        {!data ? <div className="tp-body"><Skeleton h={160} /></div> : data.length === 0 ? <Empty title="No tenants match" /> : (
          <div style={{ overflow: 'auto' }}>
            <table className="tp-table">
              <thead><tr><th>Tenant</th><th>State</th><th>Plan</th><th>Billing</th><th>Sites</th><th>Active workers</th><th /></tr></thead>
              <tbody>{data.map((t) => (
                <tr key={t.tenant_id}>
                  <td>{t.name}<div className="tp-muted" style={{ fontSize: 12 }}>{t.tenant_id}</div></td>
                  <td>{t.status === 'active' ? <Status tone="ok">Active</Status> : <Status tone="bad">Suspended</Status>}</td>
                  <td>{t.managed ? t.plan : <span className="tp-muted">no plan recorded</span>}{t.subscription_status && t.subscription_status !== 'active' && <div><Status tone="risk">{t.subscription_status}</Status></div>}</td>
                  <td>{t.managed ? `${t.billing_source}${t.manual_kind ? ` · ${t.manual_kind}` : ''}` : '—'}{t.expires_at && <div className="tp-muted" style={{ fontSize: 12 }}>to {when(t.expires_at)}</div>}</td>
                  <td className="tp-num">{t.sites_in_use}{t.licensed_sites != null ? ` / ${t.licensed_sites}` : ''}</td>
                  <td className="tp-num">{t.active_workers}{t.worker_band ? ` (band ${t.worker_band})` : ''} {t.allowance_state === 'near' && <Status tone="risk">Near</Status>}{t.allowance_state === 'over' && <Status tone="bad">Over</Status>}</td>
                  <td><button className="tp-btn" onClick={() => setOpen(t)}>Manage</button></td>
                </tr>))}</tbody>
            </table>
          </div>)}
      </section>
      {open === 'new' && <NewTenant plans={plans} onClose={() => setOpen(null)} onDone={reload} />}
      {open && open !== 'new' && <ManageTenant t={open} plans={plans} onClose={() => setOpen(null)} onDone={reload} />}
    </>
  )
}

function SubscriptionForm({ plans, initial, onSubmit, busy, label }: { plans: PlanDef[]; initial?: Partial<SubscriptionInput>; onSubmit: (s: SubscriptionInput) => void; busy: boolean; label: string }) {
  const [f, setF] = useState<SubscriptionInput>({ plan_key: 'optimise', licensed_sites: 1, worker_band: '250', manual_kind: 'pilot', discount_pct: 0, reason: '', reference: '', expires_at: null, ...initial })
  const approved = new Set(plans.filter((p) => p.status === 'approved').map((p) => p.plan_key))
  const draftOnly = !approved.has(f.plan_key)
  return (
    <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); onSubmit({ ...f, reference: f.reference || null, expires_at: f.expires_at ? new Date(f.expires_at).toISOString() : null }) }}>
      <div className="tp-cols2">
        <label className="tp-field">Plan<select value={f.plan_key} onChange={(e) => setF({ ...f, plan_key: e.target.value })}>{['essentials', 'optimise', 'orchestrate', 'network'].map((k) => <option key={k} value={k}>{k}{approved.has(k) ? '' : ' (not approved)'}</option>)}</select></label>
        <label className="tp-field">Arrangement<select value={f.manual_kind} onChange={(e) => setF({ ...f, manual_kind: e.target.value })}>{['contract', 'pilot', 'demo', 'complimentary'].map((k) => <option key={k} value={k}>{k}</option>)}</select></label>
      </div>
      {draftOnly && !['pilot', 'demo'].includes(f.manual_kind) && <Banner tone="warn" title="Plan not approved">Only pilot or demo arrangements may use a plan version that has not been approved.</Banner>}
      <div className="tp-cols2">
        <label className="tp-field">Licensed sites<input type="number" min={1} max={500} value={f.licensed_sites} onChange={(e) => setF({ ...f, licensed_sites: Number(e.target.value) })} /></label>
        <label className="tp-field">Active-worker band<select value={f.worker_band} onChange={(e) => setF({ ...f, worker_band: e.target.value })}>{[['250', 'up to 250'], ['500', '251–500'], ['1000', '501–1,000'], ['1000+', 'over 1,000']].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></label>
      </div>
      <div className="tp-cols2">
        <label className="tp-field">Negotiated discount (%)<input type="number" min={0} max={100} value={f.discount_pct} onChange={(e) => setF({ ...f, discount_pct: Number(e.target.value) })} /></label>
        <label className="tp-field">Ends (optional)<input type="date" value={f.expires_at?.slice(0, 10) ?? ''} onChange={(e) => setF({ ...f, expires_at: e.target.value || null })} /></label>
      </div>
      <label className="tp-field">Contract / invoice reference<input value={f.reference ?? ''} onChange={(e) => setF({ ...f, reference: e.target.value })} /></label>
      <label className="tp-field">Reason (at least 10 characters; kept in the history)<input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} required /></label>
      <button className="tp-btn primary" disabled={busy || f.reason.trim().length < 10}>{label}</button>
      <p className="tp-muted" style={{ fontSize: 12 }}>This records an arrangement made outside Stripe; no card is taken and no Stripe customer is created. Stripe is not connected.</p>
    </form>
  )
}

function NewTenant({ plans, onClose, onDone }: { plans: PlanDef[]; onClose: () => void; onDone: () => void }) {
  const [t, setT] = useState({ id: '', name: '', email: '', sites: '' })
  const [err, setErr] = useState<string | null>(null)
  const [invite, setInvite] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [withPlan, setWithPlan] = useState(true)
  async function go(s?: SubscriptionInput) {
    setBusy(true); setErr(null)
    try {
      const r = await createTenant({ tenant_id: t.id.trim(), name: t.name.trim(), first_admin: { email: t.email.trim() }, initial_site_ids: t.sites.split(',').map((x) => x.trim()).filter(Boolean), ...(s ? { subscription: s } : {}) })
      setInvite(r.invite_path ? `${window.location.origin}${r.invite_path}` : 'The administrator already has a password; no invitation was needed.'); onDone()
    } catch (e) { setErr(msg(e)) } finally { setBusy(false) }
  }
  return (
    <Drawer title="Create tenant" onClose={onClose}>
      {invite ? (
        <div className="tp-stack"><Banner tone="info" title="Tenant created">Send this one-time link to the first administrator. It is shown once and expires; Tempo does not send email yet.</Banner><code style={{ wordBreak: 'break-all' }}>{invite}</code></div>
      ) : (
        <div className="tp-stack">
          {err && <Banner tone="bad" title="Problem">{err}</Banner>}
          <label className="tp-field">Tenant ID (lower case, digits, underscore)<input value={t.id} onChange={(e) => setT({ ...t, id: e.target.value })} /></label>
          <label className="tp-field">Organisation name<input value={t.name} onChange={(e) => setT({ ...t, name: e.target.value })} /></label>
          <label className="tp-field">First administrator’s email<input type="email" value={t.email} onChange={(e) => setT({ ...t, email: e.target.value })} /></label>
          <label className="tp-field">Site IDs (comma separated)<input value={t.sites} onChange={(e) => setT({ ...t, sites: e.target.value })} placeholder="mel_dc_01" /></label>
          <label className="tp-row"><input type="checkbox" checked={withPlan} onChange={(e) => setWithPlan(e.target.checked)} /> Record a plan and allowance now</label>
          {withPlan ? <SubscriptionForm plans={plans} busy={busy} label="Create tenant with plan" initial={{ licensed_sites: Math.max(1, t.sites.split(',').filter((x) => x.trim()).length) }} onSubmit={(s) => void go(s)} />
            : <button className="tp-btn primary" disabled={busy || !t.id || !t.name || !t.email || !t.sites} onClick={() => void go()}>Create tenant without a plan</button>}
        </div>)}
    </Drawer>
  )
}

function ManageTenant({ t, plans, onClose, onDone }: { t: TenantRow; plans: PlanDef[]; onClose: () => void; onDone: () => void }) {
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [hist, setHist] = useState<{ at: string; actor: string; action: string; reason: string }[] | null>(null)
  useEffect(() => { subscriptionHistory(t.tenant_id).then(setHist).catch(() => setHist([])) }, [t.tenant_id])
  async function act(fn: () => Promise<unknown>, close = true) { setBusy(true); setErr(null); try { await fn(); onDone(); if (close) onClose() } catch (e) { setErr(msg(e)) } finally { setBusy(false) } }
  return (
    <Drawer title={t.name} onClose={onClose}>
      <div className="tp-stack">
        {err && <Banner tone="bad" title="Problem">{err}</Banner>}
        <div className="tp-row">{t.status === 'active'
          ? <button className="tp-btn danger" disabled={busy} onClick={() => { if (window.confirm(`Suspend ${t.name}? Everyone in this organisation is signed out of access immediately.`)) void act(() => setTenantStatus(t.tenant_id, 'suspended')) }}>Suspend tenant</button>
          : <button className="tp-btn primary" disabled={busy} onClick={() => void act(() => setTenantStatus(t.tenant_id, 'active'))}>Reactivate tenant</button>}</div>
        {t.billing_source === 'stripe' ? <Banner tone="info" title="Billed through Stripe">The plan is not changed here.</Banner>
          : <><h3 style={{ margin: '8px 0 0', fontSize: 14 }}>{t.managed ? 'Change the plan or allowance' : 'Record a plan'}</h3>
            <SubscriptionForm plans={plans} busy={busy} label="Save" initial={{ plan_key: plans.find((p) => p.name === t.plan)?.plan_key ?? 'optimise', licensed_sites: t.licensed_sites ?? Math.max(1, t.sites_in_use), worker_band: t.worker_band ?? '250', manual_kind: t.manual_kind ?? 'pilot' }}
              onSubmit={(s) => void act(() => setSubscription(t.tenant_id, s))} /></>}
        <details><summary>Commercial history</summary>
          {!hist ? <Skeleton h={50} /> : hist.length === 0 ? <p className="tp-muted">Nothing recorded.</p> : <ul style={{ paddingLeft: 18, fontSize: 13 }}>{hist.map((h, i) => <li key={i}>{when(h.at)} — {h.action.replace('_', ' ')}{h.reason ? ` — “${h.reason}”` : ''} <span className="tp-muted">({h.actor.slice(0, 8)})</span></li>)}</ul>}
        </details>
      </div>
    </Drawer>
  )
}

function Plans() {
  const { data, err, reload } = useLoad(listPlans, [])
  const [f, setF] = useState<{ plan_key: string; name: string; price: string; notes: string } | null>(null)
  const [e2, setE2] = useState<string | null>(null)
  async function act(fn: () => Promise<unknown>) { setE2(null); try { await fn(); setF(null); reload() } catch (e) { setE2(msg(e)) } }
  return (
    <>
      <PageHead title="Plans" sub="Versioned plan definitions. Prices are indicative proposals until a version is approved; the feature matrix is not agreed, so no feature is gated by plan yet." />
      {(err || e2) && <Banner tone="bad" title="Problem">{err ?? e2}</Banner>}
      <section className="tp-card">
        {!data ? <div className="tp-body"><Skeleton h={120} /></div> : (
          <table className="tp-table"><thead><tr><th>Plan</th><th>Version</th><th>Per site / month (AUD)</th><th>Status</th><th /></tr></thead>
            <tbody>{data.map((p) => (
              <tr key={p.id}><td>{p.name}</td><td className="tp-num">v{p.version}</td><td className="tp-num">{p.monthly_price_per_site_aud == null ? 'custom' : p.monthly_price_per_site_aud.toLocaleString('en-AU')}{p.indicative && <span className="tp-muted"> · indicative</span>}</td>
                <td>{p.status === 'approved' ? <Status tone="ok">Approved</Status> : p.status === 'draft' ? <Status tone="risk">Draft</Status> : <Status tone="neutral">Retired</Status>}</td>
                <td>{p.status === 'draft' && <button className="tp-btn" onClick={() => void act(() => approvePlan(p.id))}>Approve</button>}<button className="tp-btn" onClick={() => setF({ plan_key: p.plan_key, name: p.name, price: p.monthly_price_per_site_aud == null ? '' : String(p.monthly_price_per_site_aud), notes: '' })}>New version</button></td></tr>))}</tbody></table>)}
      </section>
      {f && <Drawer title={`New ${f.plan_key} version`} onClose={() => setF(null)}>
        <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void act(() => newPlanVersion({ plan_key: f.plan_key, name: f.name, monthly_price_per_site_aud: f.price === '' ? null : Number(f.price), notes: f.notes })) }}>
          <label className="tp-field">Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
          <label className="tp-field">Monthly price per site, AUD (blank for custom)<input type="number" min={0} value={f.price} onChange={(e) => setF({ ...f, price: e.target.value })} /></label>
          <label className="tp-field">Notes<input value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></label>
          <button className="tp-btn primary">Create draft</button>
          <p className="tp-muted" style={{ fontSize: 12 }}>A change is always a new draft. Another platform admin approves it (when there is more than one).</p>
        </form></Drawer>}
    </>
  )
}

function Support() {
  const { data, err, reload } = useLoad(listGrants, [])
  const [f, setF] = useState({ tenant: '', reason: '', hours: 1, cats: 'diagnostics', sites: '' })
  const [open, setOpen] = useState(false)
  const [e2, setE2] = useState<string | null>(null)
  async function act(fn: () => Promise<unknown>) { setE2(null); try { await fn(); setOpen(false); reload() } catch (e) { setE2(msg(e)) } }
  return (
    <>
      <PageHead title="Support access" sub="Time-boxed, reasoned grants. A grant is not ambient access to all tenants, and it ends on its own."><button className="tp-btn primary" onClick={() => setOpen(true)}>New grant</button></PageHead>
      {(err || e2) && <Banner tone="bad" title="Problem">{err ?? e2}</Banner>}
      <section className="tp-card">
        {!data ? <div className="tp-body"><Skeleton h={100} /></div> : data.length === 0 ? <Empty title="No support grants" /> : (
          <table className="tp-table"><thead><tr><th>Tenant</th><th>Reason</th><th>Scope</th><th>Until</th><th>State</th><th /></tr></thead>
            <tbody>{data.map((g: SupportGrant) => (
              <tr key={g.grant_id}><td>{g.target_tenant_id}</td><td>{g.reason}</td><td>{g.action_categories.join(', ')}<div className="tp-muted" style={{ fontSize: 12 }}>{g.site_ids.join(', ')}</div></td><td>{when(g.expires_at)}</td>
                <td>{g.state === 'live' ? <Status tone="risk">Live</Status> : <Status tone="neutral">{g.state}</Status>}</td>
                <td>{g.state === 'live' && <button className="tp-btn danger" onClick={() => void act(() => endGrant(g.grant_id))}>End now</button>}</td></tr>))}</tbody></table>)}
      </section>
      <p className="tp-muted" style={{ fontSize: 12 }}>Opening a tenant as a support session (with a persistent banner and a read-only diagnostic view) is not built yet; this page records and ends the grants it would rely on.</p>
      {open && <Drawer title="New support grant" onClose={() => setOpen(false)}>
        <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void act(() => createGrant({ target_tenant_id: f.tenant.trim(), reason: f.reason.trim(), hours: f.hours, action_categories: f.cats.split(',').map((x) => x.trim()).filter(Boolean), site_ids: f.sites.split(',').map((x) => x.trim()).filter(Boolean) })) }}>
          <label className="tp-field">Tenant ID<input value={f.tenant} onChange={(e) => setF({ ...f, tenant: e.target.value })} required /></label>
          <label className="tp-field">Reason (at least 10 characters)<input value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} required /></label>
          <div className="tp-cols2"><label className="tp-field">Hours (max 8)<input type="number" min={0.5} max={8} step={0.5} value={f.hours} onChange={(e) => setF({ ...f, hours: Number(e.target.value) })} /></label>
            <label className="tp-field">Categories<input value={f.cats} onChange={(e) => setF({ ...f, cats: e.target.value })} /></label></div>
          <label className="tp-field">Site IDs (comma separated)<input value={f.sites} onChange={(e) => setF({ ...f, sites: e.target.value })} required /></label>
          <button className="tp-btn primary" disabled={f.reason.trim().length < 10}>Grant</button>
        </form></Drawer>}
    </>
  )
}

function Audit() {
  const { data, err } = useLoad(platformAudit, [])
  return (
    <>
      <PageHead title="Audit" sub="Platform and tenant security events, newest first." />
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      <section className="tp-card">{!data ? <div className="tp-body"><Skeleton h={160} /></div> : (
        <div style={{ overflow: 'auto', maxHeight: 640 }}><table className="tp-table"><thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Tenant</th><th>Result</th></tr></thead>
          <tbody>{data.map((r: AuditRow) => <tr key={r.event_id}><td>{when(r.at)}</td><td>{r.actor_type} <span className="tp-muted">{r.actor_id.slice(0, 8)}</span></td><td>{r.action}{r.reason_code ? <div className="tp-muted" style={{ fontSize: 12 }}>{r.reason_code}</div> : null}</td><td>{r.tenant_id ?? '—'}</td><td>{r.decision}</td></tr>)}</tbody></table></div>)}</section>
    </>
  )
}

function Admins() {
  const [email, setEmail] = useState('')
  const [res, setRes] = useState<{ tone: 'info' | 'bad'; text: string } | null>(null)
  return (
    <>
      <PageHead title="Platform admins" sub="Adding an admin needs your fresh two-step verification. You get a one-time invitation link to pass to them." />
      {res && <Banner tone={res.tone} title={res.tone === 'info' ? 'Done' : 'Problem'}>{res.text}</Banner>}
      <section className="tp-card"><div className="tp-body tp-stack" style={{ maxWidth: 420 }}>
        <label className="tp-field">Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
        <button className="tp-btn primary" disabled={!email} onClick={() => { setRes(null); addPlatformAdmin(email.trim()).then((r) => setRes({ tone: 'info', text: r.invite_path ? `Send ${email} this one-time link (shown once; Tempo does not email invitations yet): ${window.location.origin}${r.invite_path}` : `${email} already has a password and can sign in.` })).catch((e) => setRes({ tone: 'bad', text: msg(e) })) }}>Add platform admin</button>
      </div></section>
    </>
  )
}

/** The platform operator surface: separate from the customer shell, with its own banner, navigation and sign-out. */
export default function PlatformConsole() {
  const { status, access, signOut } = useTempoContext()
  if (status === 'loading') return <div className="tp-app" style={{ padding: 32 }}><Skeleton h={28} w={240} /></div>
  if (status !== 'authenticated' || !access) return <LoginPage />
  if (!access.platform_admin) return <div className="tp-app" style={{ padding: 32 }}><Banner tone="bad" title="Not a platform operator">This area is for Tempo platform staff. <NavLink to="/">Back to your organisation</NavLink></Banner></div>
  return (
    <div className="tp-app">
      <div className="tp-devbar" role="note" style={{ background: 'var(--tp-charcoal)', color: 'var(--tp-on-chrome)' }}>PLATFORM OPERATOR CONSOLE — you are acting on customer organisations. Every action is audited under your name.</div>
      <header className="tp-topbar"><div className="tp-brand"><img src="/brand/tempo-lockup-dark.png" alt="Tempo" /></div><div className="tp-spacer" />
        <div className="tp-user"><div><div>platform operator</div><small>{access.email ?? access.username}{access.mfa_verified ? ' · MFA' : ' · MFA required'}</small></div><button className="tp-iconbtn" onClick={() => void signOut()}>Sign out</button></div></header>
      <div className="tp-shell" style={{ display: 'grid', gridTemplateColumns: '200px 1fr', gap: 16, padding: 16 }}>
        <nav aria-label="Platform" className="tp-stack">
          {[['/platform', 'Tenants', true], ['/platform/plans', 'Plans'], ['/platform/support', 'Support access'], ['/platform/audit', 'Audit'], ['/platform/admins', 'Platform admins'], ['/platform/account', 'My account & MFA']].map(([to, l, end]) => <NavLink key={to as string} to={to as string} end={!!end} className="tp-btn" style={{ textDecoration: 'none' }}>{l}</NavLink>)}
        </nav>
        <main id="main" tabIndex={-1}>
          {!access.mfa_verified && <Banner tone="warn" title="Two-step verification required">Platform actions need it. <NavLink to="/platform/account">Set it up or verify now</NavLink>.</Banner>}
          <Routes><Route index element={<Tenants />} /><Route path="plans" element={<Plans />} /><Route path="support" element={<Support />} /><Route path="audit" element={<Audit />} /><Route path="admins" element={<Admins />} /><Route path="account" element={<AccountPage />} /></Routes>
        </main>
      </div>
    </div>
  )
}
