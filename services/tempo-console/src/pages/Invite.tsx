import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { acceptInvite, inviteInfo } from '../api/session'
import { Banner } from '../components/ui'

/** Set a password from a one-time invitation / reset link. Outside the app shell: no session needed. */
export default function InvitePage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const nav = useNavigate()
  const [info, setInfo] = useState<{ email: string; username: string | null; purpose: string; password_rules: { min_length: number } } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [username, setUsername] = useState('')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { inviteInfo(token).then((i) => { setInfo(i); setUsername(i.username ?? '') }).catch((e) => setErr(e instanceof ApiError ? e.message : 'This link is not valid.')) }, [token])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setErr(null)
    try { await acceptInvite(token, pw, username || undefined); nav('/?welcome=1', { replace: true }) } catch (x) { setErr(x instanceof ApiError ? x.message : 'Something went wrong') } finally { setBusy(false) }
  }
  return (
    <div className="tp-app tp-login">
      <div className="tp-card">
        <img src="/brand/tempo-lockup-light.png" alt="Tempo" />
        <h1 style={{ fontSize: 20, margin: '8px 0 4px' }}>{info?.purpose === 'reset' ? 'Reset your password' : 'Welcome — set your password'}</h1>
        {err && <Banner tone="bad" title="Can’t continue">{err}</Banner>}
        {info && (
          <form onSubmit={submit} className="tp-stack">
            <p className="tp-muted" style={{ margin: 0 }}>Account: <b>{info.email}</b></p>
            <label className="tp-field">Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" placeholder={info.email} /></label>
            <label className="tp-field">New password (at least {info.password_rules.min_length} characters)<input type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="new-password" /></label>
            <label className="tp-field">Repeat password<input type="password" value={pw2} onChange={(e) => setPw2(e.target.value)} autoComplete="new-password" /></label>
            {pw2 && pw !== pw2 && <span role="alert" style={{ color: 'var(--tp-red-ink)' }}>Passwords do not match.</span>}
            <button className="tp-btn primary" disabled={busy || pw.length < info.password_rules.min_length || pw !== pw2}>{busy ? 'Saving…' : 'Set password'}</button>
            <p className="tp-muted" style={{ fontSize: 12.5, margin: 0 }}>This link works once. Administrators are asked to set up an authenticator app at first sign-in.</p>
          </form>
        )}
      </div>
    </div>
  )
}
