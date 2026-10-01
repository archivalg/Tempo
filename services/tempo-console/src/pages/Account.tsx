import { QrCode } from '../components/QrCode'
import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { changePassword, mfaConfirm, mfaEnroll } from '../api/session'
import { Banner, PageHead, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'

export default function AccountPage() {
  const { access, reload } = useTempoContext()
  const [cur, setCur] = useState('')
  const [n1, setN1] = useState('')
  const [n2, setN2] = useState('')
  const [msg, setMsg] = useState<{ tone: 'info' | 'bad'; text: string } | null>(null)
  const [enrol, setEnrol] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const run = async (fn: () => Promise<void>) => { setBusy(true); setMsg(null); try { await fn() } catch (e) { setMsg({ tone: 'bad', text: e instanceof ApiError ? e.message : 'Failed' }) } finally { setBusy(false) } }

  const savePw = (e: FormEvent) => { e.preventDefault(); void run(async () => { await changePassword(cur, n1); setCur(''); setN1(''); setN2(''); setMsg({ tone: 'info', text: 'Password changed. Your other devices were signed out.' }) }) }
  return (
    <>
      <PageHead title="Account" sub={`${access?.email ?? access?.username ?? ''} · ${access?.tenant_id ?? 'platform'}`} />
      {msg && <Banner tone={msg.tone} title={msg.text} />}
      {access?.mfa_required && <Banner tone="warn" title="Set up an authenticator app to use your administrator permissions">Until you do, admin actions are unavailable to you.</Banner>}
      <div className="tp-cols2" style={{ alignItems: 'start' }}>
        <section className="tp-card"><header><h2>Change password</h2></header>
          <form className="tp-body tp-stack" onSubmit={savePw}>
            <label className="tp-field">Current password<input type="password" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" /></label>
            <label className="tp-field">New password (12+ characters)<input type="password" value={n1} onChange={(e) => setN1(e.target.value)} autoComplete="new-password" /></label>
            <label className="tp-field">Repeat new password<input type="password" value={n2} onChange={(e) => setN2(e.target.value)} autoComplete="new-password" /></label>
            <button className="tp-btn primary" disabled={busy || !cur || n1.length < 12 || n1 !== n2}>Change password</button>
          </form>
        </section>
        <section className="tp-card"><header><h2>Two-step verification</h2>{access?.mfa_enabled ? <Status tone="ok">On</Status> : <Status tone={access?.mfa_required ? 'bad' : 'neutral'}>Off</Status>}</header>
          <div className="tp-body tp-stack">
            {access?.mfa_enabled ? <p className="tp-muted" style={{ margin: 0 }}>You’ll be asked for a code from your authenticator app each time you sign in. If you lose the device, an administrator can reset it.</p> : !enrol ? (
              <>
                <p style={{ margin: 0 }}>Use an authenticator app (Microsoft Authenticator, Google Authenticator, 1Password…) for a second step at sign-in.</p>
                <button className="tp-btn primary" disabled={busy} onClick={() => void run(async () => setEnrol(await mfaEnroll()))}>Set up authenticator</button>
              </>
            ) : (
              <>
                <p style={{ margin: 0 }}>Scan this code with your authenticator app, or choose “enter a setup key” and type the key below it.</p>
                <QrCode value={enrol.otpauth_uri} label="QR code to add Tempo to your authenticator app" />
                <code style={{ fontSize: 18, letterSpacing: 2, wordBreak: 'break-all' }} aria-label="Setup key">{enrol.secret.match(/.{1,4}/g)?.join(' ')}</code>
                <p className="tp-muted" style={{ fontSize: 12.5, margin: 0 }}>Account: {access?.email}. Time-based, 6 digits. This key is shown only now.</p>
                <label className="tp-field">Enter the 6-digit code to confirm<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={8} autoComplete="one-time-code" /></label>
                <button className="tp-btn primary" disabled={busy || code.trim().length < 6} onClick={() => void run(async () => { await mfaConfirm(code); setEnrol(null); setCode(''); await reload(); setMsg({ tone: 'info', text: 'Two-step verification is on.' }) })}>Confirm and turn on</button>
              </>
            )}
          </div>
        </section>
      </div>
    </>
  )
}
