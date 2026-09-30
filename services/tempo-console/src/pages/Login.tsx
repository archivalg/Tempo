import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, BASE_URL } from '../api/client'
import { devLogin, getAuthConfig, listDevIdentities, mfaVerify, passwordLogin, type AuthConfig, type DevIdentity } from '../api/session'
import { Banner } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'

export default function LoginPage() {
  const { reload } = useTempoContext()
  const [cfg, setCfg] = useState<AuthConfig | null>(null)
  const [ids, setIds] = useState<DevIdentity[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [user, setUser] = useState('')
  const [pw, setPw] = useState('')
  const [challenge, setChallenge] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const methods = cfg?.methods ?? []

  useEffect(() => {
    getAuthConfig().then((c) => {
      setCfg(c)
      if (c.methods?.includes('dev-local') || c.provider === 'dev-local') listDevIdentities().then(setIds).catch(() => setIds([]))
    }).catch((e) => setErr(e instanceof Error ? e.message : 'Cannot reach the Tempo API'))
  }, [])

  async function guard<T>(fn: () => Promise<T>) {
    setBusy(true); setErr(null)
    try { return await fn() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Sign-in failed'); return undefined } finally { setBusy(false) }
  }
  async function submit(e: FormEvent) {
    e.preventDefault()
    const r = await guard(() => passwordLogin(user, pw))
    if (!r) return
    setPw('')
    if (r.status === 'mfa_required') { setChallenge(r.challenge); return }
    await reload()
  }
  async function submitCode(e: FormEvent) {
    e.preventDefault()
    if (!challenge) return
    const r = await guard(() => mfaVerify(challenge, code))
    if (r) { setCode(''); setChallenge(null); await reload() }
  }

  return (
    <div className="tp-app tp-login">
      <div className="tp-card">
        <img src="/brand/tempo-lockup-light.png" alt="Tempo" />
        <h1 style={{ fontSize: 20, margin: '8px 0 4px' }}>Sign in</h1>
        <p className="tp-muted" style={{ marginTop: 0 }}>Warehouse labour planning &amp; attendance.</p>
        {err && <Banner tone="bad" title="Couldn’t sign you in">{err}</Banner>}

        {challenge ? (
          <form onSubmit={submitCode} className="tp-stack">
            <p style={{ margin: 0 }}>Enter the 6-digit code from your authenticator app.</p>
            <label className="tp-field">Authentication code<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={8} autoFocus style={{ fontSize: 20, letterSpacing: 4 }} /></label>
            <div className="tp-row"><button className="tp-btn primary" disabled={busy || code.trim().length < 6}>Verify</button><button type="button" className="tp-btn" onClick={() => { setChallenge(null); setCode('') }}>Back</button></div>
          </form>
        ) : methods.includes('password') || cfg?.provider === 'password' ? (
          <form onSubmit={submit} className="tp-stack">
            <label className="tp-field">Username or email<input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="username" autoFocus /></label>
            <label className="tp-field">Password<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" /></label>
            <button className="tp-btn primary" disabled={busy || !user || !pw}>{busy ? 'Signing in…' : 'Sign in'}</button>
            <p className="tp-muted" style={{ fontSize: 12.5, margin: 0 }}>Accounts are created by invitation. Forgot your password? Ask your administrator for a reset link.</p>
          </form>
        ) : null}

        {!challenge && methods.includes('oidc') && <p><a className="tp-btn" style={{ display: 'inline-block', textDecoration: 'none' }} href={`${BASE_URL}/auth/oidc/login`}>Continue with your organisation account</a></p>}
        {cfg?.provider === 'unconfigured' && <Banner tone="warn" title="No sign-in method is configured">An administrator must enable password sign-in or connect an identity provider.</Banner>}

        {!challenge && (methods.includes('dev-local') || cfg?.provider === 'dev-local') && (
          <>
            <Banner tone="warn" title="Local development identities">{cfg?.notice} These are synthetic demo users for local testing only; their access still comes from Tempo’s own roles and grants.</Banner>
            <ul className="tp-list" aria-label="Demo identities">
              {ids.map((i) => (
                <li key={i.subject}>
                  <button className="tp-item" style={{ gridTemplateColumns: '1fr auto' }} disabled={busy} onClick={() => void guard(async () => { await devLogin(i.subject, i.email, true); await reload() })}>
                    <span><span className="t">{i.display_name ?? i.email}</span><br /><span className="s">{i.email}</span></span><span aria-hidden="true">→</span>
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
