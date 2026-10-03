import * as SecureStore from 'expo-secure-store'

/** Session and device credentials live only in the platform's secure storage (iOS Keychain / Android Keystore-backed). Never in plain storage, never in the bundle. */
export interface StoredSession { access: string; refresh: string; accessExpiresAt: string; refreshExpiresAt: string }

const SESSION = 'tempo.session.v1'
const DEVICE = 'tempo.push-device.v1'
const KIOSK = 'tempo.kiosk.v1'
const OPTS = { keychainAccessible: SecureStore.AFTER_FIRST_UNLOCK_THIS_DEVICE_ONLY }

async function read<T>(key: string): Promise<T | null> {
  try {
    const v = await SecureStore.getItemAsync(key)
    return v ? (JSON.parse(v) as T) : null
  } catch {
    return null
  }
}
const write = (key: string, v: unknown) => SecureStore.setItemAsync(key, JSON.stringify(v), OPTS)

export const loadSession = () => read<StoredSession>(SESSION)
export const saveSession = (s: StoredSession) => write(SESSION, s)
export const clearSession = () => SecureStore.deleteItemAsync(SESSION).catch(() => undefined)

export const loadPushDeviceId = () => read<string>(DEVICE)
export const savePushDeviceId = (id: string) => write(DEVICE, id)
export const clearPushDeviceId = () => SecureStore.deleteItemAsync(DEVICE).catch(() => undefined)

export interface KioskDevice { credential: string; deviceId: string; siteIds: string[]; tenantId: string }
export const loadKiosk = () => read<KioskDevice>(KIOSK)
export const saveKiosk = (k: KioskDevice) => write(KIOSK, k)
export const clearKiosk = () => SecureStore.deleteItemAsync(KIOSK).catch(() => undefined)
