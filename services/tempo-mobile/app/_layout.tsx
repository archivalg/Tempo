import * as Notifications from 'expo-notifications'
import { Slot, useRouter } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { useEffect, useRef } from 'react'
import { SafeAreaProvider } from 'react-native-safe-area-context'
import { ackNotification } from '../src/api/endpoints'
import * as store from '../src/auth/storage'
import { SessionProvider, useSession } from '../src/auth/session'
import { NetworkProvider } from '../src/net/network'
import { routeForDeepLink } from '../src/push/links'
import { configureNotificationHandler } from '../src/push/register'

configureNotificationHandler()

/** Notification taps and arrivals. A tap while signed out waits for sign-in, then goes to the right screen. */
function NotificationRouting() {
  const router = useRouter()
  const { state } = useSession()
  const pending = useRef<string | null>(null)
  const last = Notifications.useLastNotificationResponse()
  const handled = useRef<string | null>(null)

  const open = (data: Record<string, unknown> | undefined) => {
    const route = routeForDeepLink(typeof data?.deep_link === 'string' ? data.deep_link : null)
    if (state === 'signedIn') router.push(route as never); else pending.current = route
  }
  const acknowledge = async (data: Record<string, unknown> | undefined) => {
    const nid = typeof data?.notification_id === 'string' ? data.notification_id : null
    if (nid && state === 'signedIn') await ackNotification(nid, (await store.loadPushDeviceId()) ?? undefined).catch(() => undefined)   // only the app can say it was received
  }
  useEffect(() => {
    const a = Notifications.addNotificationReceivedListener((n) => void acknowledge(n.request.content.data))
    const b = Notifications.addNotificationResponseReceivedListener((r) => { void acknowledge(r.notification.request.content.data); open(r.notification.request.content.data) })
    return () => { a.remove(); b.remove() }
  }, [state]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (last && handled.current !== last.notification.request.identifier) { handled.current = last.notification.request.identifier; open(last.notification.request.content.data) }
  }, [last]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (state === 'signedIn' && pending.current) { const r = pending.current; pending.current = null; router.push(r as never) } }, [state]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}

export default function Root() {
  return (
    <SafeAreaProvider>
      <SessionProvider>
        <NetworkProvider>
          <StatusBar style="light" />
          <NotificationRouting />
          <Slot />
        </NetworkProvider>
      </SessionProvider>
    </SafeAreaProvider>
  )
}
