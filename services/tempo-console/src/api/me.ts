import { apiRequest } from './client'

export interface MeProfile { user_id: string; worker_id: string; display_name: string | null; company: string; site: { site_id: string; name: string; timezone: string }; employment_type: string }
export interface MeShift { id: string; site_name: string; timezone: string; role: string; zone: string; start_at: string; end_at: string; local_date: string; overnight: boolean; duration_minutes: number; dst_change_during_shift: boolean; break_minutes: number | null; instructions: string | null; status: 'scheduled' | 'needs_reconfirmation' }
export interface MeChange { id: string; kind: 'added' | 'changed' | 'cancelled'; before: { start_at?: string; end_at?: string } | null; after: { start_at?: string; end_at?: string; instructions?: string | null } | null; at: string; seen: boolean }
export interface MeOffer { id: string; site_name: string; timezone: string; role: string; zone: string; start_at: string; end_at: string; break_minutes: number | null; instructions: string | null; expires_at: string | null; status_for_me?: string }
export interface MeAvailability { id: string; start_at: string; end_at: string; status: string; source: string; editable: boolean }
export interface MeLeave { id: string; kind: string; start_date: string; end_date: string; reason: string | null; status: 'pending' | 'approved' | 'rejected' | 'cancelled'; decision_note: string | null }
export interface MeSession { id: string; state: string; started_at: string; ended_at: string | null; approval: string; corrected: boolean; worked_minutes: number; break_minutes: number; payable_minutes: number | null; punches: { kind: string; at: string; source: string }[] }
export interface MePrefs { push_enabled: boolean; roster_published: boolean; shift_changes: boolean; offers: boolean; reminders: boolean; decisions: boolean; reminder_lead_minutes: number; lead_choices: number[]; sms_opt_in: boolean; sms_number: string | null; sms_available: boolean }

export const meProfile = () => apiRequest<MeProfile>('/me/profile')
export const meShifts = () => apiRequest<{ timezone: string; shifts: MeShift[] }>('/me/shifts')
export const meChanges = () => apiRequest<{ unseen: number; changes: MeChange[] }>('/me/changes')
export const meChangesSeen = () => apiRequest('/me/changes/seen', { method: 'POST' })
export const meOffers = () => apiRequest<{ offers: MeOffer[] }>('/me/offers')
export const meRespond = (id: string, action: 'accept' | 'decline') => apiRequest(`/me/offers/${id}/respond`, { method: 'POST', body: { action } })
export const meAvailability = () => apiRequest<{ entries: MeAvailability[] }>('/me/availability')
export const meAddAvailability = (start_at: string, end_at: string) => apiRequest('/me/availability', { method: 'POST', body: { start_at, end_at } })
export const meRemoveAvailability = (id: string) => apiRequest(`/me/availability/${id}`, { method: 'DELETE' })
export const meLeave = () => apiRequest<{ requests: MeLeave[] }>('/me/leave')
export const meRequestLeave = (b: { kind: string; start_date: string; end_date: string; reason?: string }) => apiRequest('/me/leave', { method: 'POST', body: b })
export const meCancelLeave = (id: string) => apiRequest(`/me/leave/${id}`, { method: 'DELETE' })
export const meAttendance = () => apiRequest<{ timezone: string; current_state: string; sessions: MeSession[] }>('/me/attendance')
export const mePrefs = () => apiRequest<MePrefs>('/me/notification-preferences')
export const mePutPrefs = (p: Omit<MePrefs, 'lead_choices' | 'sms_available'>) => apiRequest<MePrefs>('/me/notification-preferences', { method: 'PUT', body: p })
