import { apiFetch } from './client'
import type {
  ClockInResponse,
  ClockMethod,
  ClockOutResponse,
  CredentialEnrollResponse,
  SiteAttendanceEntry,
  TempoContext,
  UpcomingShift,
  WhoamiResponse,
} from './types'

interface CredentialArgs {
  method: ClockMethod
  pin?: string
  nfcTagId?: string
}

function credentialBody({ method, pin, nfcTagId }: CredentialArgs) {
  return { method, pin: pin ?? null, nfc_tag_id: nfcTagId ?? null }
}

export function whoami(context: TempoContext, credential: CredentialArgs): Promise<WhoamiResponse> {
  return apiFetch<WhoamiResponse>('/attendance/whoami', context, { method: 'POST', body: credentialBody(credential) })
}

export function clockIn(
  context: TempoContext,
  siteId: string,
  credential: CredentialArgs,
  gps?: { latitude: number; longitude: number },
): Promise<ClockInResponse> {
  return apiFetch<ClockInResponse>('/attendance/clock-in', context, {
    method: 'POST',
    body: { site_id: siteId, ...credentialBody(credential), gps: gps ?? null },
  })
}

export function clockOut(context: TempoContext, credential: CredentialArgs): Promise<ClockOutResponse> {
  return apiFetch<ClockOutResponse>('/attendance/clock-out', context, { method: 'POST', body: credentialBody(credential) })
}

export function enrollCredential(
  context: TempoContext,
  workerId: string,
  credential: { pin?: string; nfcTagId?: string },
): Promise<CredentialEnrollResponse> {
  return apiFetch<CredentialEnrollResponse>('/attendance/credentials', context, {
    method: 'POST',
    body: { worker_id: workerId, pin: credential.pin || null, nfc_tag_id: credential.nfcTagId || null },
  })
}

export function getWorkerShifts(context: TempoContext, workerId: string): Promise<UpcomingShift[]> {
  return apiFetch<UpcomingShift[]>(`/workers/${workerId}/shifts`, context)
}

export function getSiteAttendance(context: TempoContext, siteId: string, sinceHours = 24): Promise<SiteAttendanceEntry[]> {
  return apiFetch<SiteAttendanceEntry[]>(`/sites/${siteId}/attendance?since_hours=${sinceHours}`, context)
}
