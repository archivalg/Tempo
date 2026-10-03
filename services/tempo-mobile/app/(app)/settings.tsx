import { Linking, Text } from 'react-native'
import { useEffect, useState } from 'react'
import { ApiError } from '../../src/api/client'
import { getPrefs, putPrefs } from '../../src/api/endpoints'
import type { NotificationPrefs } from '../../src/api/types'
import { APP_ENV, APP_VERSION } from '../../src/config'
import { useSession } from '../../src/auth/session'
import { useResource } from '../../src/hooks/useResource'
import { enablePush, pushPermission, type PushStatus } from '../../src/push/register'
import { Banner, Button, Card, ErrorState, Field, H2, Loading, P, Screen, Toggle } from '../../src/ui/kit'
import { colors } from '../../src/ui/theme'

const CATS: [keyof NotificationPrefs, string, string][] = [
  ['roster_published', 'Roster published', 'When your roster for a week is published.'], ['shift_changes', 'Shift changes and cancellations', 'When a shift you have is moved or cancelled.'],
  ['offers', 'Shift offers', 'When your manager offers you a shift.'], ['reminders', 'Shift reminders', 'A reminder before each shift.'], ['decisions', 'Request decisions', 'When leave and other requests are decided.'],
]
const leadText = (m: number) => (m >= 60 ? `${m / 60} hour${m === 60 ? '' : 's'}` : `${m} minutes`)

export default function Settings() {
  const { profile, signOut } = useSession()
  const r = useResource(() => getPrefs(), [])
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null)
  const [perm, setPerm] = useState<PushStatus>('undetermined')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { if (r.data) setPrefs(r.data) }, [r.data])
  useEffect(() => { void pushPermission().then(setPerm) }, [])
  const save = async (patch: Partial<NotificationPrefs>) => {
    if (!prefs) return
    const next = { ...prefs, ...patch }
    setPrefs(next); setErr(null)
    try { setPrefs(await putPrefs({ push_enabled: next.push_enabled, roster_published: next.roster_published, shift_changes: next.shift_changes, offers: next.offers, reminders: next.reminders, decisions: next.decisions, reminder_lead_minutes: next.reminder_lead_minutes, sms_opt_in: next.sms_opt_in, sms_number: next.sms_number })) }
    catch (e) { setPrefs(r.data); setErr(e instanceof ApiError ? (e.kind === 'network' ? 'No connection. Your change was not saved.' : e.message) : 'Could not save.') }
  }
  const turnOn = async () => { setBusy(true); setPerm(await enablePush(true)); setBusy(false) }
  return (
    <Screen onRefresh={r.refresh} refreshing={r.refreshing}>
      <Card><H2>{profile?.display_name ?? 'You'}</H2><P muted>{profile?.company} · {profile?.site.name}</P></Card>
      <H2>Notifications</H2>
      {r.loading && !prefs ? <Loading /> : null}
      {r.error && !prefs && <ErrorState message={r.error} onRetry={r.reload} />}
      {err ? <Banner tone="bad" title={err} /> : null}
      {perm === 'unsupported' && <Banner tone="info" title="This device cannot receive push notifications">Simulators and emulators cannot. Use a real phone.</Banner>}
      {perm === 'denied' && <Banner tone="warn" title="Notifications are blocked for Tempo"><Text onPress={() => void Linking.openSettings()} style={{ textDecorationLine: 'underline' }}>Open phone settings</Text> to allow them.</Banner>}
      {perm === 'unavailable' && <Banner tone="warn" title="Push is not set up for this build">This build has no push project configured, so there is no notification token to register.</Banner>}
      {(perm === 'undetermined') && <Button title="Allow notifications on this phone" onPress={() => void turnOn()} busy={busy} />}
      {prefs && (
        <Card>
          {!prefs.company_push_enabled && <Banner tone="warn" title="Your company has turned push notifications off" />}
          <Toggle label="Push notifications" value={prefs.push_enabled} onChange={(v) => void save({ push_enabled: v })} />
          {CATS.map(([k, l, h]) => <Toggle key={k} label={l} hint={h} value={prefs[k] as boolean} onChange={(v) => void save({ [k]: v } as Partial<NotificationPrefs>)} disabled={!prefs.push_enabled} />)}
          <Text style={{ fontWeight: '600', color: colors.ink2, marginTop: 4 }}>Remind me before a shift</Text>
          <Text style={{ color: colors.muted, fontSize: 13 }}>Currently {leadText(prefs.reminder_lead_minutes)} before.</Text>
          <Text style={{ flexDirection: 'row' }}>{prefs.lead_choices.map((m) => <Text key={m} onPress={() => void save({ reminder_lead_minutes: m })} accessibilityRole="button" style={{ padding: 8, color: m === prefs.reminder_lead_minutes ? colors.green : colors.focus, fontWeight: m === prefs.reminder_lead_minutes ? '800' : '500' }}>{leadText(m)}  </Text>)}</Text>
          <P small muted>Lock-screen messages never show times, places or names. Open the app for details.</P>
        </Card>
      )}
      {prefs?.sms_available && (
        <Card>
          <H2>Text messages</H2>
          <P small muted>Used only for urgent shift changes, and only if you turn it on. Your company sets a monthly limit.</P>
          <Toggle label="Send me urgent changes by text" value={prefs.sms_opt_in} onChange={(v) => void save({ sms_opt_in: v })} />
          <Field label="Mobile number (+61…)" value={prefs.sms_number ?? ''} onChangeText={(t) => setPrefs({ ...prefs, sms_number: t })} onEndEditing={() => void save({ sms_number: prefs.sms_number })} keyboardType="phone-pad" />
        </Card>
      )}
      <Button title="Sign out" kind="secondary" onPress={() => void signOut()} />
      <P small muted>Tempo {APP_VERSION}{APP_ENV === 'production' ? '' : ` (${APP_ENV})`}</P>
    </Screen>
  )
}
