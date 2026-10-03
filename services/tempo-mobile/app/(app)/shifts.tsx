import { useRouter } from 'expo-router'
import { useMemo } from 'react'
import { Pressable, Text, View } from 'react-native'
import { getChanges, getShifts } from '../../src/api/endpoints'
import type { Shift } from '../../src/api/types'
import { useSession } from '../../src/auth/session'
import { useResource } from '../../src/hooks/useResource'
import { clock, day, hours, localDate, shiftRange } from '../../src/lib/time'
import { Card, Empty, ErrorState, H2, Loading, P, Pill, Row, Screen } from '../../src/ui/kit'
import { colors } from '../../src/ui/theme'

export function groupLabel(date: string, today: string): string {
  const d = (n: number) => { const x = new Date(`${today}T00:00:00Z`); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10) }
  if (date === today) return 'Today'
  if (date === d(1)) return 'Tomorrow'
  return ''
}

export default function Shifts() {
  const router = useRouter()
  const { profile } = useSession()
  const shifts = useResource(() => getShifts(), [])
  const changes = useResource(() => getChanges(), [])
  const tz = profile?.site.timezone ?? shifts.data?.timezone ?? 'UTC'
  const today = localDate(new Date(), tz)
  const groups = useMemo(() => {
    const m = new Map<string, Shift[]>()
    for (const s of shifts.data?.shifts ?? []) { if (s.local_date < today && new Date(s.end_at) < new Date()) continue; (m.get(s.local_date) ?? m.set(s.local_date, []).get(s.local_date)!).push(s) }
    return [...m.entries()]
  }, [shifts.data, today])
  const unseen = changes.data?.unseen ?? 0
  return (
    <Screen onRefresh={() => { shifts.refresh(); changes.refresh() }} refreshing={shifts.refreshing}>
      <Text style={{ color: colors.muted }}>{profile ? `${profile.company} · ${profile.site.name}` : ''}</Text>
      {unseen > 0 && (
        <Card onPress={() => router.push('/changes')} accessibilityLabel="Roster changes">
          <Row><Pill tone="warn">{unseen} roster change{unseen === 1 ? '' : 's'}</Pill><Text style={{ color: colors.ink2, flex: 1 }}>Tap to see what changed.</Text></Row>
        </Card>
      )}
      {shifts.loading && !shifts.data ? <Loading /> : null}
      {shifts.error && <ErrorState message={shifts.data ? `${shifts.error} Showing what was loaded${shifts.updatedAt ? ` at ${clock(shifts.updatedAt.toISOString(), tz)}` : ''}.` : shifts.error} onRetry={shifts.reload} />}
      {shifts.data && groups.length === 0 && !shifts.error ? <Empty title="No upcoming shifts">Published shifts appear here. A roster you have not been told about is still a draft.</Empty> : null}
      {groups.map(([date, list]) => (
        <View key={date} style={{ gap: 8 }}>
          <H2>{groupLabel(date, today) ? `${groupLabel(date, today)} · ` : ''}{day(list[0].start_at, tz)}</H2>
          {list.map((s) => (
            <Card key={s.id} onPress={() => router.push(`/shifts/${s.id}`)} accessibilityLabel={`Shift ${s.role} ${shiftRange(s.start_at, s.end_at, s.timezone, s.overnight)}`}>
              <Row style={{ justifyContent: 'space-between' }}>
                <Text style={{ fontSize: 20, fontWeight: '800', color: colors.ink }}>{clock(s.start_at, s.timezone)} – {clock(s.end_at, s.timezone)}</Text>
                {s.status === 'needs_reconfirmation' ? <Pill tone="warn">Confirm change</Pill> : s.overnight ? <Pill tone="info">Overnight</Pill> : null}
              </Row>
              <P>{s.role} · {s.zone}</P>
              <P small muted>{s.site_name} · {hours(s.duration_minutes)}{s.break_minutes ? ` · ${s.break_minutes} min break` : ''}</P>
            </Card>
          ))}
        </View>
      ))}
      <Pressable onPress={() => router.push('/notifications')} accessibilityRole="button"><Text style={{ color: colors.focus, textAlign: 'center', padding: 8 }}>Notifications</Text></Pressable>
    </Screen>
  )
}
