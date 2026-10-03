import { useLocalSearchParams } from 'expo-router'
import { useState } from 'react'
import { Text } from 'react-native'
import { ApiError } from '../../src/api/client'
import { getOffers, respondOffer } from '../../src/api/endpoints'
import type { Offer } from '../../src/api/types'
import { useResource } from '../../src/hooks/useResource'
import { dayClock, shiftRange } from '../../src/lib/time'
import { Banner, Button, Card, Empty, ErrorState, Loading, P, Pill, Row, Screen } from '../../src/ui/kit'
import { colors } from '../../src/ui/theme'

const STATUS: Record<string, { tone: 'ok' | 'warn' | 'bad' | 'info' | 'neutral'; text: string }> = {
  open: { tone: 'info', text: 'Open to you' }, accepted: { tone: 'ok', text: 'You accepted: waiting for your manager' }, declined: { tone: 'neutral', text: 'You declined' },
  taken: { tone: 'neutral', text: 'Taken by someone else' }, expired: { tone: 'neutral', text: 'Expired' }, cancelled: { tone: 'bad', text: 'Cancelled' },
  needs_reconfirmation: { tone: 'warn', text: 'Changed: please confirm again' }, not_taken: { tone: 'neutral', text: 'Not taken' }, rejected_by_manager: { tone: 'bad', text: 'Your manager did not confirm' },
}

function OfferCard({ o, onDone, focused }: { o: Offer; onDone: () => void; focused: boolean }) {
  const [busy, setBusy] = useState<'accept' | 'decline' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const st = STATUS[o.status_for_me ?? 'open'] ?? STATUS.open
  const answer = async (a: 'accept' | 'decline') => {
    setBusy(a); setErr(null)
    try { await respondOffer(o.id, a); onDone() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Could not send your answer.') } finally { setBusy(null) }
  }
  const canAnswer = o.status_for_me === 'open' || o.status_for_me === 'accepted' || o.status_for_me === 'needs_reconfirmation'
  const overnight = new Date(o.end_local).getDate() !== new Date(o.start_local).getDate()
  return (
    <Card>
      <Row style={{ justifyContent: 'space-between' }}><Pill tone={st.tone}>{st.text}</Pill>{focused ? <Pill tone="info">From your notification</Pill> : null}</Row>
      <Text style={{ fontSize: 18, fontWeight: '800', color: colors.ink }}>{shiftRange(o.start_at, o.end_at, o.timezone, overnight)}</Text>
      <P>{o.role} · {o.zone} · {o.site_name}</P>
      {o.break_minutes ? <P small muted>{o.break_minutes} min unpaid break</P> : null}
      {o.instructions ? <P small muted>{o.instructions}</P> : null}
      {o.expires_at ? <P small muted>Answer by {dayClock(o.expires_at, o.timezone)}</P> : null}
      {err ? <Banner tone="bad" title={err} /> : null}
      {canAnswer && o.status_for_me !== 'accepted' && <Button title="Accept this shift" onPress={() => void answer('accept')} busy={busy === 'accept'} disabled={!!busy} />}
      {canAnswer && <Button title={o.status_for_me === 'accepted' ? 'Withdraw' : 'Decline'} kind="secondary" onPress={() => void answer('decline')} busy={busy === 'decline'} disabled={!!busy} />}
    </Card>
  )
}

export default function Offers() {
  const { focus } = useLocalSearchParams<{ focus?: string }>()
  const r = useResource(() => getOffers(), [])
  const list = r.data?.offers ?? []
  const open = list.filter((o) => ['open', 'accepted', 'needs_reconfirmation'].includes(o.status_for_me ?? 'open'))
  const past = list.filter((o) => !open.includes(o))
  return (
    <Screen onRefresh={r.refresh} refreshing={r.refreshing}>
      {r.loading && !r.data ? <Loading /> : null}
      {r.error && <ErrorState message={r.error} onRetry={r.reload} />}
      {r.data && list.length === 0 ? <Empty title="No shift offers">When your manager offers you an extra shift it appears here. Accepting does not put it on your roster until your manager confirms.</Empty> : null}
      {open.map((o) => <OfferCard key={o.id} o={o} onDone={r.reload} focused={focus === o.id} />)}
      {past.length > 0 && <Text style={{ fontWeight: '700', color: colors.ink2, marginTop: 8 }}>Earlier offers</Text>}
      {past.map((o) => <OfferCard key={o.id} o={o} onDone={r.reload} focused={focus === o.id} />)}
    </Screen>
  )
}
