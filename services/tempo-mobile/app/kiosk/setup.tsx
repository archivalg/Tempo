import { useRouter } from 'expo-router'
import { useState } from 'react'
import { ApiError } from '../../src/api/client'
import * as store from '../../src/auth/storage'
import { enrolDevice } from '../../src/kiosk/api'
import { Banner, Button, Card, Field, H1, P, Screen } from '../../src/ui/kit'

/** A manager creates the device in Tempo (Administration → Kiosk devices) and gets a one-time code; entering it here makes THIS tablet that kiosk. */
export default function KioskSetup() {
  const router = useRouter()
  const [code, setCode] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const go = async () => {
    setBusy(true); setErr(null)
    try {
      const d = await enrolDevice(code)
      await store.saveKiosk({ credential: d.device_credential, deviceId: d.device_id, siteIds: d.site_ids, tenantId: d.tenant_id })
      router.replace('/kiosk')
    } catch (e) {
      const a = e as ApiError
      setErr(a.kind === 'network' || a.kind === 'timeout' ? 'Cannot reach Tempo. This tablet has not been set up.' : 'That code is not valid or has expired. Ask a manager for a new one.')
    } finally { setBusy(false) }
  }
  return (
    <Screen>
      <H1>Set up this tablet as a kiosk</H1>
      <P>A manager creates the device in Tempo (Administration → Kiosk devices) and gives you a one-time code that works for 15 minutes.</P>
      <Card>
        <Field label="Enrolment code" value={code} onChangeText={setCode} autoCapitalize="none" autoCorrect={false} />
        {err ? <Banner tone="bad" title={err} /> : null}
        <Button title="Set up this kiosk" onPress={() => void go()} busy={busy} disabled={code.trim().length < 12} />
        <Button title="Back" kind="secondary" onPress={() => router.replace('/login')} />
      </Card>
      <P small muted>Once set up, this tablet opens straight to the kiosk. Leaving kiosk mode needs a manager's sign-in.</P>
    </Screen>
  )
}
