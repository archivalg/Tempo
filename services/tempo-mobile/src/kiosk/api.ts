import { api, ApiError } from '../api/client'
import { APP_VERSION } from '../config'
import { Platform } from 'react-native'
import type { KioskDevice } from '../auth/storage'
import type { Identity, KioskAction } from './state'
import * as Location from 'expo-location'
import type { PunchResult, WhoAmI } from '../api/types'

export type Gps = { latitude?: number; longitude?: number; accuracy_m?: number; error?: 'denied' | 'unavailable' }

/** The tablet's position at the moment of the tap, asked for ONLY when the company has switched site location checks on. Never stored on the device. */
export async function getFix(mode: string | undefined): Promise<Gps | undefined> {
  if (!mode || mode === 'off') return undefined
  try {
    const p = await Location.requestForegroundPermissionsAsync()
    if (!p.granted) return { error: 'denied' }
    const r = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced })
    return { latitude: r.coords.latitude, longitude: r.coords.longitude, accuracy_m: r.coords.accuracy ?? undefined }
  } catch {
    return { error: 'unavailable' }
  }
}

const PATH: Record<KioskAction, string> = { clock_in: '/attendance/clock-in', break_start: '/attendance/break-start', break_end: '/attendance/break-end', clock_out: '/attendance/clock-out' }

const credential = (id: Identity) => (id.mode === 'pin' ? { method: 'pin', worker_no: id.workerNo, pin: id.pin } : { method: 'qr', qr_token: id.token })

export const enrolDevice = (code: string) =>
  api<{ device_id: string; device_credential: string; site_ids: string[]; tenant_id: string }>('/kiosk/enrol', { method: 'POST', auth: false, body: { enrolment_code: code.trim(), platform: Platform.OS === 'ios' ? 'ios' : 'android', app_version: APP_VERSION } })

export const whoami = (dev: KioskDevice, id: Identity) => api<WhoAmI>('/attendance/whoami', { method: 'POST', deviceToken: dev.credential, body: { ...credential(id) } })

export const punch = (dev: KioskDevice, id: Identity, action: KioskAction, gps?: Gps) =>
  api<PunchResult>(PATH[action], { method: 'POST', deviceToken: dev.credential, body: { ...credential(id), ...(gps ? { gps } : {}), ...(action === 'clock_in' ? { site_id: dev.siteIds.length === 1 ? dev.siteIds[0] : undefined } : {}) } })

export const authoriseExit = (dev: KioskDevice, b: { username: string; password: string; code?: string; challenge?: string; purpose: 'exit' | 'reconfigure'; revoke_device: boolean }) =>
  api<{ authorised: boolean; mfa_required?: boolean; challenge?: string }>('/kiosk/exit-authorise', { method: 'POST', deviceToken: dev.credential, body: b })

/** Turns a failure into what the kiosk should say. Network and timeout failures are NEVER shown as a wrong PIN or as success. */
export function describeFailure(e: unknown): { kind: 'network' | 'refused'; message: string; deviceRevoked: boolean } {
  const a = e as ApiError
  if (a?.kind === 'network' || a?.kind === 'timeout') return { kind: 'network', message: 'Cannot reach Tempo. You have NOT been clocked. Tell your supervisor, or try again.', deviceRevoked: false }
  if (a?.status === 401 && /device/i.test(a.message)) return { kind: 'refused', message: 'This kiosk has been disabled by a manager.', deviceRevoked: true }
  if (a?.status === 401) return { kind: 'refused', message: 'Not recognised. Check your number and PIN, or show your QR code again.', deviceRevoked: false }
  if (a?.status === 403) return { kind: 'refused', message: 'Locked for now. Please see a supervisor.', deviceRevoked: false }
  return { kind: 'refused', message: a?.message || 'That could not be recorded. See a supervisor.', deviceRevoked: false }
}
