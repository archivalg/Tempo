import { useEffect } from 'react'
import { Text } from 'react-native'
import { getChanges, markChangesSeen } from '../../src/api/endpoints'
import type { ShiftChange } from '../../src/api/types'
import { useSession } from '../../src/auth/session'
import { useResource } from '../../src/hooks/useResource'
import { dayClock } from '../../src/lib/time'
import { Card, Empty, ErrorState, Loading, P, Pill, Row, Screen } from '../../src/ui/kit'
import { colors } from '../../src/ui/theme'

const TONE = { added: 'ok', changed: 'warn', cancelled: 'bad' } as const
const WORD = { added: 'New shift', changed: 'Changed', cancelled: 'Cancelled' } as const

function when(c: ShiftChange, tz: string): string {
  const x = c.after ?? c.before
  return x?.start_at && x?.end_at ? `${dayClock(x.start_at, tz)} – ${dayClock(x.end_at, tz).slice(-5)}` : ''
}

export default function Changes() {
  const { profile } = useSession()
  const tz = profile?.site.timezone ?? 'UTC'
  const r = useResource(() => getChanges(), [])
  useEffect(() => { if (r.data && r.data.unseen > 0) void markChangesSeen().catch(() => undefined) }, [r.data])
  return (
    <Screen onRefresh={r.refresh} refreshing={r.refreshing}>
      {r.loading && !r.data ? <Loading /> : null}
      {r.error && <ErrorState message={r.error} onRetry={r.reload} />}
      {r.data && r.data.changes.length === 0 ? <Empty title="No roster changes">When your manager publishes or changes your roster, it shows here.</Empty> : null}
      {(r.data?.changes ?? []).map((c) => (
        <Card key={c.id}>
          <Row style={{ justifyContent: 'space-between' }}><Pill tone={TONE[c.kind]}>{WORD[c.kind]}</Pill><Text style={{ color: colors.muted, fontSize: 12 }}>{dayClock(c.at, tz)}</Text></Row>
          <P>{when(c, tz)}</P>
          {c.kind === 'changed' && c.before?.start_at ? <P small muted>Was {dayClock(c.before.start_at, tz)} – {dayClock(c.before.end_at ?? c.before.start_at, tz).slice(-5)}</P> : null}
          {(c.after?.instructions) ? <P small muted>{c.after.instructions}</P> : null}
        </Card>
      ))}
    </Screen>
  )
}
