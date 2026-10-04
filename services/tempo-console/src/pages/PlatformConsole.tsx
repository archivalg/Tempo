import { useCallback, useEffect, useState } from 'react'
import { Link, NavLink, Route, Routes, useNavigate, useParams } from 'react-router-dom'
import {
  addPlatformAdmin, approvePlan, createGrant, createTenant, endGrant, getDiagnostics, inviteTenantAdmin, listGrants, openSupport, listPlans, newPlanVersion, platformAudit, setSubscription, setTenantStatus, subscriptionHistory, tenantOverview,
  type AuditRow, type Diagnostics, type PlanDef, type SubscriptionInput, type SupportGrant, type TenantRow,
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

function InviteAdmin({ tenantId }: { tenantId: string }) {
  const [email, setEmail] = useState('')
  const [link, setLink] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  return (
    <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); setBusy(true); setErr(null); setLink(null); inviteTenantAdmin(tenantId, email.trim()).then((r) => { setLink(`${window.location.origin}${r.invite_path}`); setEmail('') }).catch((x) => setErr(msg(x))).finally(() => setBusy(false)) }}>
      <h3 style={{ margin: '8px 0 0', fontSize: 14 }}>Invite an administrator for this organisation</h3>
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      {link && <Banner tone="info" title="One-time link (shown once)">Send it to them privately; Tempo does not email it. <code style={{ wordBreak: 'break-all' }}>{link}</code></Banner>}
      <label className="tp-field">Email<input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></label>
      <button className="tp-btn" disabled={busy || !email}>Invite administrator</button>
      <p className="tp-muted" style={{ fontSize: 12, margin: 0 }}>They get the same sites as the organisation's existing administrators and set up two-step verification at first sign-in. Further users are invited by that organisation's administrators under Administration → Users.</p>
    </form>
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
        <InviteAdmin tenantId={t.tenant_id} />
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
                <td>{g.state === 'live' && <span className="tp-row"><Link className="tp-btn primary" to={`/platform/support/${g.grant_id}`} style={{ textDecoration: 'none' }}>Open for support</Link><button className="tp-btn danger" onClick={() => void act(() => endGrant(g.grant_id))}>End now</button></span>}</td></tr>))}</tbody></table>)}
      </section>
      <p className="tp-muted" style={{ fontSize: 12 }}><b>Open for support</b> shows a read-only diagnostic view of the tenant (counts, states and health within the granted sites; no names or personal data). Operational changes and exports are not offered. The session ends when the grant expires or is ended, and the server refuses it from then on.</p>
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

function SupportSession() {
  const { grantId = '' } = useParams()
  const nav = useNavigate()
  const [d, setD] = useState<Diagnostics | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [left, setLeft] = useState('')
  useEffect(() => {
    setD(null); setErr(null)   // switching grant discards the previous tenant's data
    openSupport(grantId).then(() => getDiagnostics(grantId)).then(setD).catch((e) => setErr(msg(e)))
  }, [grantId])
  useEffect(() => {
    if (!d) return
    const tick = () => {
      const ms = new Date(d.session.expires_at).getTime() - Date.now()
      if (ms <= 0) { setD(null); setErr('This support session has expired. Nothing more can be read.'); return }
      setLeft(`${Math.floor(ms / 3600000)}h ${String(Math.floor((ms % 3600000) / 60000)).padStart(2, '0')}m`)
    }
    tick(); const t = setInterval(tick, 15000); return () => clearInterval(t)
  }, [d])
  const end = async () => { try { await endGrant(grantId) } catch { /* already ended */ } setD(null); nav('/platform/support') }
  if (err) return <><Banner tone="bad" title="Support session unavailable">{err}</Banner><Link to="/platform/support">Back to support access</Link></>
  if (!d) return <Skeleton h={200} />
  return (
    <>
      <div role="status" style={{ position: 'sticky', top: 0, zIndex: 5, background: '#7a1f1f', color: '#fff', padding: '10px 14px', borderRadius: 6, marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <strong>SUPPORT SESSION — {d.tenant.name} ({d.tenant.tenant_id})</strong><span>read-only diagnostics · {d.session.site_ids.join(', ')} · ends in {left}</span>
        <span style={{ flex: 1 }}>“{d.session.reason}”</span><button className="tp-btn" onClick={() => void end()}>End session</button>
      </div>
      <div className="tp-kpis">
        {[['Active workers', d.workers_by_status.active ?? 0], ['Inactive', d.workers_by_status.inactive ?? 0], ['Clocked in now', d.open_attendance_sessions], ['Open exceptions', Object.values(d.open_exceptions_by_kind).reduce((a, b) => a + b, 0)]].map(([l, v]) => <div key={l as string} className="tp-card tp-kpi"><div className="lbl">{l}</div><div className="val">{v as number}</div></div>)}
      </div>
      <section className="tp-card"><header><h2>Plan</h2></header><div className="tp-body">{d.plan.managed ? <>{d.plan.plan?.name} · sites {d.plan.sites_in_use}/{d.plan.licensed_sites} · workers {d.plan.active_workers} · allowance {d.plan.allowance_state}</> : <>No plan recorded (unmanaged).</>}</div></section>
      <section className="tp-card"><header><h2>Sites</h2></header><table className="tp-table"><tbody>{d.sites.map((s) => <tr key={s.site_id}><td>{s.name}<div className="tp-muted" style={{ fontSize: 12 }}>{s.site_id}</div></td><td>{s.timezone}</td><td>{s.operating_mode}</td></tr>)}</tbody></table></section>
      <section className="tp-card"><header><h2>Rosters</h2></header>{d.rosters.length === 0 ? <div className="tp-body"><Empty title="No rosters" /></div> : <table className="tp-table"><thead><tr><th>Site</th><th>Week</th><th>Version</th><th>State</th><th>Source</th></tr></thead><tbody>{d.rosters.map((r, i) => <tr key={i}><td>{r.site_id}</td><td>{r.week_start}</td><td>v{r.version_no}</td><td>{r.state}</td><td>{r.source}</td></tr>)}</tbody></table>}</section>
      <section className="tp-card"><header><h2>Recent imports</h2></header>{d.imports.length === 0 ? <div className="tp-body"><Empty title="No imports" /></div> : <table className="tp-table"><thead><tr><th>When</th><th>Data</th><th>Via</th><th>State</th><th>Rows</th><th>Rejected</th></tr></thead><tbody>{d.imports.map((b, i) => <tr key={i}><td>{when(b.at)}</td><td>{b.data_class}{b.entity ? ` / ${b.entity}` : ''}</td><td>{b.channel}</td><td>{b.state}</td><td className="tp-num">{b.rows}</td><td className="tp-num">{b.errors}</td></tr>)}</tbody></table>}</section>
      <section className="tp-card"><header><h2>Connections</h2></header>{d.connections.length === 0 ? <div className="tp-body"><Empty title="No connections" /></div> : <table className="tp-table"><tbody>{d.connections.map((c, i) => <tr key={i}><td>{c.source_system}</td><td>{c.site_id}</td><td>{c.status}</td></tr>)}</tbody></table>}</section>
      <section className="tp-card"><header><h2>Recent security events for this tenant</h2></header><div style={{ overflow: 'auto', maxHeight: 360 }}><table className="tp-table"><tbody>{d.recent_security_events.map((e, i) => <tr key={i}><td>{when(e.at)}</td><td>{e.actor_type}</td><td>{e.action}</td><td>{e.decision}</td></tr>)}</tbody></table></div></section>
      <p className="tp-muted" style={{ fontSize: 12 }}>{d.limits} Every view here is recorded in the audit log under your name and this grant.</p>
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
          <Routes><Route index element={<Tenants />} /><Route path="plans" element={<Plans />} /><Route path="support" element={<Support />} /><Route path="support/:grantId" element={<SupportSession />} /><Route path="audit" element={<Audit />} /><Route path="admins" element={<Admins />} /><Route path="account" element={<AccountPage />} /></Routes>
        </main>
      </div>
    </div>
  )
}
