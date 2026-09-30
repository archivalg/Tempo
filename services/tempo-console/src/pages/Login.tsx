import { useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { devLogin, getAuthConfig, listDevIdentities, type AuthConfig, type DevIdentity } from '../api/session'
import { Banner } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { BASE_URL } from '../api/client'

export default function LoginPage() {
  const { reload } = useTempoContext()
  const [cfg, setCfg] = useState<AuthConfig | null>(null)
  const [ids, setIds] = useState<DevIdentity[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    getAuthConfig().then((c) => {
      setCfg(c)
      if (c.provider === 'dev-local') listDevIdentities().then(setIds).catch(() => setIds([]))
    }).catch((e) => setErr(e instanceof Error ? e.message : 'Cannot reach the Tempo API'))
  }, [])

  async function signIn(i: DevIdentity) {
    setBusy(true); setErr(null)
    try { await devLogin(i.subject, i.email, true); await reload() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Sign-in failed') } finally { setBusy(false) }
  }

  return (
    <div className="tp-app tp-login">
      <div className="tp-card">
        <img src="/brand/tempo-lockup-light.png" alt="Tempo" />
        <h1 style={{ fontSize: 20, margin: '8px 0 4px' }}>Sign in</h1>
        <p className="tp-muted" style={{ marginTop: 0 }}>Warehouse labour planning &amp; attendance.</p>
        {err && <Banner tone="bad" title="Sign-in problem">{err}</Banner>}
        {cfg?.provider === 'oidc' && <a className="tp-btn primary" style={{ display: 'inline-block', textDecoration: 'none' }} href={`${BASE_URL}/auth/login`}>Continue with your organisation account</a>}
        {cfg?.provider === 'unconfigured' && <Banner tone="warn" title="No identity provider is configured">An administrator must configure OIDC before anyone can sign in.</Banner>}
        {cfg?.provider === 'dev-local' && (
          <>
            <Banner tone="warn" title="Local development identity">{cfg.notice} Identities below are synthetic demo users; their access still comes from Tempo's own roles and grants.</Banner>
            <ul className="tp-list" aria-label="Demo identities">
              {ids.map((i) => (
                <li key={i.subject}>
                  <button className="tp-item" style={{ gridTemplateColumns: '1fr auto' }} disabled={busy} onClick={() => void signIn(i)}>
                    <span><span className="t">{i.display_name ?? i.email}</span><br /><span className="s">{i.email}</span></span>
                    <span aria-hidden="true">→</span>
                  </button>
                </li>
              ))}
              {ids.length === 0 && <li className="tp-muted">No demo identities exist yet. Run <code>python -m app.cli bootstrap-ensemble-demo</code>.</li>}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}
