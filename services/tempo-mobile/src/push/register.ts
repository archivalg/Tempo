import * as Device from 'expo-device'
import * as Notifications from 'expo-notifications'
import { Platform } from 'react-native'
import { registerPushDevice, removePushDevice } from '../api/endpoints'
import { APP_VERSION, EAS_PROJECT_ID } from '../config'
import * as store from '../auth/storage'

export type PushStatus = 'granted' | 'denied' | 'undetermined' | 'unsupported' | 'unavailable'

/** Lock-screen text is chosen by the server and is generic; the app never adds details to it. */
export function configureNotificationHandler(): void {
  Notifications.setNotificationHandler({ handleNotification: async () => ({ shouldShowBanner: true, shouldShowList: true, shouldPlaySound: false, shouldSetBadge: false }) })
}

export async function pushPermission(): Promise<PushStatus> {
  if (!Device.isDevice) return 'unsupported'   // simulators and emulators cannot receive real push
  const p = await Notifications.getPermissionsAsync()
  return p.granted ? 'granted' : p.canAskAgain ? 'undetermined' : 'denied'
}

/** Asks for permission (only when the person chose to), gets this phone's push token and gives it to Tempo. Returns the resulting status. */
export async function enablePush(ask: boolean): Promise<PushStatus> {
  const cur = await pushPermission()
  if (cur === 'unsupported') return cur
  let status = cur
  if (status !== 'granted' && ask && status !== 'denied') {
    const r = await Notifications.requestPermissionsAsync()
    status = r.granted ? 'granted' : 'denied'
  }
  if (status !== 'granted') return status
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', { name: 'Tempo', importance: Notifications.AndroidImportance.DEFAULT })
  }
  if (!EAS_PROJECT_ID) return 'unavailable'   // no Expo project is configured for this build, so there is no push token to register
  try {
    const t = await Notifications.getExpoPushTokenAsync({ projectId: EAS_PROJECT_ID })
    const d = await registerPushDevice({ token: t.data, platform: Platform.OS === 'ios' ? 'ios' : 'android', app_version: APP_VERSION, label: Device.deviceName ?? undefined })
    await store.savePushDeviceId(d.id)
    return 'granted'
  } catch {
    return 'unavailable'
  }
}

/** Called when signing out: tells Tempo to stop sending this person's notifications to this phone. */
export async function unregisterPush(): Promise<void> {
  const id = await store.loadPushDeviceId()
  if (id) {
    await removePushDevice(id).catch(() => undefined)
    await store.clearPushDeviceId()
  }
}
