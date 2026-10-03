import { useState } from 'react'
import { Alert, Text, View } from 'react-native'
import { ApiError } from '../../src/api/client'
import { addAvailability, cancelLeave, getAvailability, getLeave, removeAvailability, requestLeave } from '../../src/api/endpoints'
import type { LeaveRequest } from '../../src/api/types'
import { useSession } from '../../src/auth/session'
import { useResource } from '../../src/hooks/useResource'
import { dayClock } from '../../src/lib/time'
import { Banner, Button, Card, Empty, ErrorState, Field, H2, Loading, P, Pill, Row, Screen } from '../../src/ui/kit'
import { DateTimeField } from '../../src/ui/DateTimeField'
import { colors } from '../../src/ui/theme'

const KINDS = [['annual', 'Annual leave'], ['personal', 'Personal / sick'], ['unpaid', 'Unpaid'], ['other', 'Other']] as const
const LEAVE_TONE = { pending: 'warn', approved: 'ok', rejected: 'bad', cancelled: 'neutral' } as const
const LEAVE_TEXT = { pending: 'Waiting for your manager', approved: 'Approved', rejected: 'Declined', cancelled: 'Cancelled' } as const
const ymd = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

/** Converts a wall-clock time the person picked into the exact instant in the SITE's time zone (so a phone in another zone, or a daylight-saving change, cannot shift it). */
export function zonedInstant(d: Date, tz: string): string {
  const wall = Date.UTC(d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes())
  let guess = wall
  for (let i = 0; i < 2; i++) {
    const parts = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).formatToParts(new Date(guess))
    const g = (t: string) => Number(parts.find((p) => p.type === t)!.value)
    const seen = Date.UTC(g('year'), g('month') - 1, g('day'), g('hour'), g('minute'))
    guess += wall - seen
  }
  return new Date(guess).toISOString()
}

export default function Requests() {
  const { profile } = useSession()
  const tz = profile?.site.timezone ?? 'UTC'
  const leave = useResource(() => getLeave(), [])
  const avail = useResource(() => getAvailability(), [])
  const [kind, setKind] = useState<(typeof KINDS)[number][0]>('annual')
  const [from, setFrom] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 7); return d })
  const [to, setTo] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 7); return d })
  const [reason, setReason] = useState('')
  const [aFrom, setAFrom] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 2); d.setHours(8, 0, 0, 0); return d })
  const [aTo, setATo] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 2); d.setHours(17, 0, 0, 0); return d })
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [ok, setOk] = useState<string | null>(null)
  const run = async (key: string, fn: () => Promise<unknown>, done: string, after: () => void) => {
    setBusy(key); setErr(null); setOk(null)
    try { await fn(); setOk(done); after() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Could not save.') } finally { setBusy(null) }
  }
  return (
    <Screen onRefresh={() => { leave.refresh(); avail.refresh() }} refreshing={leave.refreshing}>
      {err ? <Banner tone="bad" title={err} /> : null}
      {ok ? <Banner tone="ok" title={ok} /> : null}
      <H2>Leave requests</H2>
      {leave.loading && !leave.data ? <Loading /> : null}
      {leave.error && <ErrorState message={leave.error} onRetry={leave.reload} />}
      {leave.data && leave.data.requests.length === 0 ? <Empty title="No leave requests" /> : null}
      {(leave.data?.requests ?? []).map((r: LeaveRequest) => (
        <Card key={r.id}>
          <Row style={{ justifyContent: 'space-between' }}><Pill tone={LEAVE_TONE[r.status]}>{LEAVE_TEXT[r.status]}</Pill><Text style={{ color: colors.muted }}>{KINDS.find((k) => k[0] === r.kind)?.[1]}</Text></Row>
          <P>{r.start_date} to {r.end_date}</P>
          {r.decision_note ? <P small muted>Manager: {r.decision_note}</P> : null}
          {(r.status === 'pending' || r.status === 'approved') && <Button title="Cancel this request" kind="secondary" busy={busy === r.id} onPress={() => Alert.alert('Cancel leave?', 'Your manager will be told.', [{ text: 'Keep it' }, { text: 'Cancel leave', style: 'destructive', onPress: () => void run(r.id, () => cancelLeave(r.id), 'Leave cancelled.', leave.reload) }])} />}
        </Card>
      ))}
      <Card>
        <H2>Ask for leave</H2>
        <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 8 }}>
          {KINDS.map(([k, l]) => <Button key={k} title={l} kind={kind === k ? 'primary' : 'secondary'} onPress={() => setKind(k)} />)}
        </View>
        <DateTimeField label="First day" value={from} onChange={(d) => { setFrom(d); if (d > to) setTo(d) }} minimum={new Date()} />
        <DateTimeField label="Last day" value={to} onChange={setTo} minimum={from} />
        <Field label="Reason (optional)" value={reason} onChangeText={setReason} maxLength={300} />
        <Button title="Send request" busy={busy === 'leave'} onPress={() => void run('leave', () => requestLeave({ kind, start_date: ymd(from), end_date: ymd(to), reason: reason || undefined }), 'Request sent. You will be notified of the decision.', () => { setReason(''); leave.reload() })} />
        <P small muted>Days are in {tz}. Your manager approves or declines.</P>
      </Card>
      <H2>Times I cannot work</H2>
      {(avail.data?.entries ?? []).map((a) => (
        <Card key={a.id}>
          <P>{dayClock(a.start_at, tz)} to {dayClock(a.end_at, tz)}</P>
          <Row style={{ justifyContent: 'space-between' }}><Pill tone={a.status === 'leave' ? 'ok' : 'neutral'}>{a.status === 'leave' ? 'Leave' : a.source === 'tempo_employee' ? 'From you' : 'Set by your manager'}</Pill>
            {a.editable ? <Button title="Remove" kind="secondary" busy={busy === a.id} onPress={() => void run(a.id, () => removeAvailability(a.id), 'Removed.', avail.reload)} /> : null}</Row>
        </Card>
      ))}
      {avail.data && avail.data.entries.length === 0 ? <Empty title="Nothing marked" /> : null}
      <Card>
        <H2>Mark time I cannot work</H2>
        <DateTimeField label="From" value={aFrom} onChange={(d) => { setAFrom(d); if (d >= aTo) setATo(new Date(d.getTime() + 3600_000)) }} withTime minimum={new Date()} />
        <DateTimeField label="Until" value={aTo} onChange={setATo} withTime minimum={aFrom} />
        <Button title="Save" busy={busy === 'avail'} onPress={() => void run('avail', () => addAvailability(zonedInstant(aFrom, tz), zonedInstant(aTo, tz)), 'Saved. Your manager will not roster you for this time.', avail.reload)} />
        <P small muted>Times are {tz} time. This takes effect straight away and your manager can see it.</P>
      </Card>
    </Screen>
  )
}
