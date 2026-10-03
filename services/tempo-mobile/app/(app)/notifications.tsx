import { useRouter } from 'expo-router'
import { Text } from 'react-native'
import { getInbox, readNotification } from '../../src/api/endpoints'
import { useSession } from '../../src/auth/session'
import { useResource } from '../../src/hooks/useResource'
import { dayClock } from '../../src/lib/time'
import { routeForDeepLink } from '../../src/push/links'
import { Card, Empty, ErrorState, Loading, P, Pill, Row, Screen } from '../../src/ui/kit'
import { colors } from '../../src/ui/theme'

export default function Notifications() {
  const router = useRouter()
  const { profile } = useSession()
  const tz = profile?.site.timezone ?? 'UTC'
  const r = useResource(() => getInbox(), [])
  return (
    <Screen onRefresh={r.refresh} refreshing={r.refreshing}>
      {r.loading && !r.data ? <Loading /> : null}
      {r.error && <ErrorState message={r.error} onRetry={r.reload} />}
      {r.data && r.data.items.length === 0 ? <Empty title="No notifications" /> : null}
      {(r.data?.items ?? []).map((n) => (
        <Card key={n.id} onPress={() => { void readNotification(n.id).catch(() => undefined); router.push(routeForDeepLink(n.deep_link) as never) }} accessibilityLabel={n.title}>
          <Row style={{ justifyContent: 'space-between' }}>{n.read ? <Text style={{ color: colors.muted }}>Read</Text> : <Pill tone="info">New</Pill>}<Text style={{ color: colors.muted, fontSize: 12 }}>{dayClock(n.created_at, tz)}</Text></Row>
          <Text style={{ fontSize: 16, fontWeight: '700', color: colors.ink }}>{n.title}</Text>
          {n.body ? <P small muted>{n.body}</P> : null}
        </Card>
      ))}
    </Screen>
  )
}
