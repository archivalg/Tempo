import { Text } from 'react-native'
import { getAttendance } from '../../src/api/endpoints'
import { useResource } from '../../src/hooks/useResource'
import { clock, dayClock, hours } from '../../src/lib/time'
import { Banner, Card, Empty, ErrorState, Loading, P, Pill, Row, Screen } from '../../src/ui/kit'
import { colors } from '../../src/ui/theme'

const STATE = { not_clocked_in: ['neutral', 'Not clocked in'], working: ['ok', 'Clocked in'], on_break: ['warn', 'On a break'] } as const
const KIND: Record<string, string> = { clock_in: 'Clocked in', break_start: 'Break started', break_end: 'Break ended', clock_out: 'Clocked out' }

export default function Attendance() {
  const r = useResource(() => getAttendance(), [])
  const tz = r.data?.timezone ?? 'UTC'
  const cur = r.data ? STATE[r.data.current_state as keyof typeof STATE] ?? STATE.not_clocked_in : null
  return (
    <Screen onRefresh={r.refresh} refreshing={r.refreshing}>
      {r.loading && !r.data ? <Loading /> : null}
      {r.error && <ErrorState message={r.error} onRetry={r.reload} />}
      {cur && <Card><Row><Pill tone={cur[0]}>{cur[1]}</Pill></Row><P small muted>You clock in and out at the kiosk on site. This list is what Tempo recorded.</P></Card>}
      {r.data && r.data.sessions.length === 0 ? <Empty title="No clockings in the last 30 days" /> : null}
      {(r.data?.sessions ?? []).map((s) => (
        <Card key={s.id}>
          <Row style={{ justifyContent: 'space-between' }}>
            <Text style={{ fontSize: 17, fontWeight: '800', color: colors.ink }}>{dayClock(s.started_at, tz)}{s.ended_at ? ` – ${clock(s.ended_at, tz)}` : ' – open'}</Text>
            {s.approval === 'approved' ? <Pill tone="ok">Approved</Pill> : <Pill tone="warn">Awaiting approval</Pill>}
          </Row>
          <P small muted>Worked {hours(s.worked_minutes)} · break {hours(s.break_minutes)}{s.payable_minutes != null ? ` · payable ${hours(s.payable_minutes)}` : ' · payable hours appear when approved'}{s.corrected ? ' · corrected by your manager' : ''}</P>
          {s.punches.map((p, i) => <P key={i} small>{clock(p.at, tz)} {KIND[p.kind] ?? p.kind}{p.source === 'correction' ? ' (added by your manager)' : ''}</P>)}
        </Card>
      ))}
      {r.data && <Banner tone="info" title="Something wrong?">Ask your supervisor to correct a clocking. Original clockings are never changed; a correction is added next to them.</Banner>}
    </Screen>
  )
}
