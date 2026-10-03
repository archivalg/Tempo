import { useLocalSearchParams, useRouter } from 'expo-router'
import { useEffect, useState } from 'react'
import { ApiError } from '../../src/api/client'
import { acceptInvite, inviteInfo } from '../../src/api/endpoints'
import { useSession } from '../../src/auth/session'
import { Banner, Button, Card, Field, H1, Loading, P, Screen } from '../../src/ui/kit'

/** Opened from the invitation link (tempo://invite?token=…). The employee chooses their own username and password; nothing is typed into a shared screen. */
export default function Invite() {
  const { token } = useLocalSearchParams<{ token?: string }>()
  const router = useRouter()
  const { signIn } = useSession()
  const [info, setInfo] = useState<{ min: number } | null>(null)
  const [bad, setBad] = useState<string | null>(null)
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [p2, setP2] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (!token) { setBad('This invitation link is incomplete. Ask your manager for a new one.'); return }
    inviteInfo(token).then((i) => setInfo({ min: i.password_rules.min_length })).catch((e: ApiError) => setBad(e.kind === 'network' ? 'No connection to Tempo. Try again when you are online.' : e.message))
  }, [token])
  if (bad) return <Screen><Banner tone="bad" title="Invitation problem">{bad}</Banner><Button title="Back to sign in" kind="secondary" onPress={() => router.replace('/login')} /></Screen>
  if (!info) return <Loading label="Checking your invitation…" />
  const mismatch = p2.length > 0 && p !== p2
  const go = async () => {
    setBusy(true); setErr(null)
    try {
      await acceptInvite(String(token), u.trim(), p)
      await signIn(u.trim(), p)
      router.replace('/shifts')
    } catch (e) { setErr(e instanceof ApiError ? e.message : 'Could not finish setting up your account.') } finally { setBusy(false) }
  }
  return (
    <Screen>
      <H1>Welcome to Tempo</H1>
      <P>Choose how you will sign in. Your manager never sees your password.</P>
      <Card>
        <Field label="Choose a username" value={u} onChangeText={setU} autoCapitalize="none" autoCorrect={false} />
        <Field label={`Password (at least ${info.min} characters)`} value={p} onChangeText={setP} secureTextEntry />
        <Field label="Repeat the password" value={p2} onChangeText={setP2} secureTextEntry error={mismatch ? 'The passwords do not match.' : null} />
        {err ? <Banner tone="bad" title={err} /> : null}
        <Button title="Create my account" onPress={() => void go()} busy={busy} disabled={!u || p.length < info.min || p !== p2} />
      </Card>
    </Screen>
  )
}
