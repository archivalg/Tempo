import { useLocalSearchParams, useRouter } from 'expo-router'
import { useState } from 'react'
import { Text } from 'react-native'
import { getOffers, getShift, respondOffer } from '../../../src/api/endpoints'
import { ApiError } from '../../../src/api/client'
import { useResource } from '../../../src/hooks/useResource'
import { day, dayClock, hours, shiftRange } from '../../../src/lib/time'
import { Banner, Button, Card, ErrorState, H1, Loading, P, Pill, Row, Screen } from '../../../src/ui/kit'
import { colors } from '../../../src/ui/theme'

export default function ShiftDetail() {
  const { id } = useLocalSearchParams<{ id: string }>()
  const router = useRouter()
  const r = useResource(async () => ({ shift: await getShift(String(id)), offers: (await getOffers()).offers }), [id])
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  if (r.loading && !r.data) return <Loading />
  if (!r.data) return <Screen><ErrorState message={r.error ?? 'This shift is no longer available. It may have been changed or cancelled.'} onRetry={r.reload} /><Button title="Back to my shifts" kind="secondary" onPress={() => router.replace('/shifts')} /></Screen>
  const s = r.data.shift
  const offer = r.data.offers.find((o) => o.shift_id === s.id && o.status_for_me === 'needs_reconfirmation')
  const answer = async (action: 'accept' | 'decline') => {
    if (!offer) return
    setBusy(true); setMsg(null)
    try { await respondOffer(offer.id, action); if (action === 'decline') router.replace('/shifts'); else r.reload() } catch (e) { setMsg(e instanceof ApiError ? e.message : 'Could not send your answer.') } finally { setBusy(false) }
  }
  return (
    <Screen onRefresh={r.refresh} refreshing={r.refreshing}>
      <H1>{day(s.start_at, s.timezone)}</H1>
      {s.status === 'needs_reconfirmation' && <Banner tone="warn" title="This shift changed">Please confirm the new details below, or decline it.</Banner>}
      <Card>
        <Text style={{ fontSize: 24, fontWeight: '800', color: colors.ink }}>{shiftRange(s.start_at, s.end_at, s.timezone, s.overnight)}</Text>
        <Row>{s.overnight ? <Pill tone="info">Overnight</Pill> : null}{s.dst_change_during_shift ? <Pill tone="warn">Clocks change during this shift</Pill> : null}</Row>
        <P>{s.role} · {s.zone}</P>
        <P small muted>Length on the clock: {hours(s.duration_minutes)}{s.dst_change_during_shift ? ' (this is the real elapsed time; the clocks go forward or back during the shift)' : ''}</P>
      </Card>
      <Card>
        <P>Where: {s.site_name}</P>
        <P>Break: {s.break_minutes ? `${s.break_minutes} minutes (unpaid)` : 'not set. Ask your supervisor.'}</P>
        <Text style={{ fontWeight: '700', color: colors.ink, marginTop: 4 }}>Instructions</Text>
        <P>{s.instructions ?? 'None for this shift.'}</P>
      </Card>
      {offer && (
        <Card>
          <P>Your manager changed this shift after you accepted it.</P>
          {msg ? <Banner tone="bad" title={msg} /> : null}
          <Button title="Confirm the change" onPress={() => void answer('accept')} busy={busy} />
          <Button title="Decline this shift" kind="danger" onPress={() => void answer('decline')} disabled={busy} />
        </Card>
      )}
      <P small muted>Times are shown in {s.timezone}, the site's time zone. Clocking in and out is done at the kiosk on site.</P>
    </Screen>
  )
}
