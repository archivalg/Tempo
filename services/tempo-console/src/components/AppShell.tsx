import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import { NavLink, Outlet, useSearchParams } from 'react-router-dom'
import { listSites, type SiteSummary } from '../api/ops'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { fmtTime } from '../lib/format'
import { Banner, Skeleton } from './ui'
import LoginPage from '../pages/Login'

interface SiteCtx { sites: SiteSummary[]; site: SiteSummary | null; setSite: (id: string) => void }
const SiteContext = createContext<SiteCtx>({ sites: [], site: null, setSite: () => {} })
export const useSite = () => useContext(SiteContext)

const NAV: { to: string; label: string; perm: string; end?: boolean; group?: string }[] = [
  { to: '/', label: 'Overview', perm: 'labour.read', end: true, group: 'Operate' },
  { to: '/roster', label: 'Roster Planner', perm: 'labour.read' },
  { to: '/live', label: 'Live Operations', perm: 'labour.read' },
  { to: '/actions', label: 'Approvals', perm: 'labour.read', group: 'Decide' },
  { to: '/runs', label: 'Optimisation Studio', perm: 'labour.read' },
  { to: '/providers', label: 'Team & Skills', perm: 'labour.read', group: 'Manage' },
  { to: '/onboarding', label: 'Data & Connections', perm: 'labour.configure' },
  { to: '/admin', label: 'Administration', perm: 'labour.configure' },
]

export function AppShell() {
  const { status, access, can, signOut, error, reload } = useTempoContext()
  const [params, setParams] = useSearchParams()
  const canRead = status === 'authenticated' && can('labour.read')
  const sitesQ = useApi(() => (canRead ? listSites() : Promise.resolve([] as SiteSummary[])), [canRead, access?.tenant_id])
  const sites = sitesQ.data ?? []
  const wanted = params.get('site')
  // The URL selects a site but only ever within the server-authorised list.
  const site = useMemo(() => sites.find((s) => s.site_id === wanted) ?? sites[0] ?? null, [sites, wanted])
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 20000); return () => clearInterval(t) }, [])

  if (status === 'loading') return <div className="tp-app" style={{ padding: 32 }}><Skeleton h={28} w={240} /></div>
  if (status === 'error') return <div className="tp-app" style={{ padding: 32 }}><Banner tone="bad" title="Cannot reach the Tempo API">{error} <button className="tp-btn" onClick={() => void reload()}>Retry</button></Banner></div>
  if (status === 'anonymous' || !access) return <LoginPage />

  const setSite = (id: string) => { const p = new URLSearchParams(params); p.set('site', id); setParams(p, { replace: true }) }
  const nav = NAV.filter((n) => can(n.perm))
  return (
    <SiteContext.Provider value={{ sites, site, setSite }}>
      <div className="tp-app">
        <a className="tp-skip" href="#main">Skip to content</a>
        <div className="tp-shell">
          {access.idp === 'dev-local' && <div className="tp-devbar" role="note">Local development identity — this is not production authentication.</div>}
          <header className="tp-topbar">
            <div className="tp-brand"><img src="/brand/tempo-lockup-dark.png" alt="Tempo" /></div>
            <div className="tp-org">
              <label className="tp-sr-only" htmlFor="site-pick">Site</label>
              <select id="site-pick" className="tp-sitepick" value={site?.site_id ?? ''} onChange={(e) => setSite(e.target.value)} disabled={!sites.length}>
                {sites.length === 0 && <option value="">No sites in your access</option>}
                {sites.map((s) => (<option key={s.site_id} value={s.site_id}>{s.name}</option>))}
              </select>
              {site && (
                <div className="tp-clock" aria-live="off">
                  <strong className="tp-num">{fmtTime(now.toISOString(), site.timezone, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}</strong>
                  {site.timezone} · {site.operating_mode === 'standalone' ? 'Standalone' : 'Overlay'}
                </div>
              )}
            </div>
            <div className="tp-spacer" />
            <div className="tp-user">
              <div><div>{access.roles.map((r) => r.replace(/_/g, ' ')).join(', ') || 'no role'}</div><small>{access.tenant_id}{access.mfa_verified ? ' · MFA' : ''}</small></div>
              <button className="tp-iconbtn" onClick={() => void signOut()}>Sign out</button>
            </div>
          </header>
          <aside className="tp-side" aria-label="Primary">
            <nav>
              {nav.map((n, i) => (
                <div key={n.to} style={{ display: 'contents' }}>
                  {n.group && (i === 0 || nav[i - 1]?.group !== n.group) && <div className="tp-navgroup">{n.group}</div>}
                  <NavLink to={{ pathname: n.to, search: site ? `?site=${site.site_id}` : '' }} end={n.end}>{n.label}</NavLink>
                </div>
              ))}
            </nav>
          </aside>
          <main className="tp-main" id="main" tabIndex={-1}>
            {sitesQ.error ? <Banner tone="bad" title="Could not load your sites">Try again shortly.</Banner> : <Outlet />}
          </main>
        </div>
      </div>
    </SiteContext.Provider>
  )
}
