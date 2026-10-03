export interface Profile { user_id: string; worker_id: string; display_name: string | null; company: string; tenant_id: string; site: { site_id: string; name: string; timezone: string }; employment_type: string; server_time: string }
export interface Shift {
  id: string; site_id: string; site_name: string; timezone: string; role: string; zone: string
  start_at: string; end_at: string; start_local: string; end_local: string; local_date: string
  overnight: boolean; duration_minutes: number; dst_change_during_shift: boolean
  break_minutes: number | null; instructions: string | null; status: 'scheduled' | 'needs_reconfirmation'
}
export interface ShiftChange { id: string; kind: 'added' | 'changed' | 'cancelled'; shift_id: string | null; before: Partial<Shift> | null; after: Partial<Shift> | null; at: string; seen: boolean }
export interface Offer {
  id: string; site_name: string; timezone: string; role: string; zone: string; start_at: string; end_at: string; start_local: string; end_local: string
  break_minutes: number | null; instructions: string | null; expires_at: string | null; status: string
  my_response?: string; status_for_me?: 'open' | 'accepted' | 'declined' | 'taken' | 'expired' | 'cancelled' | 'needs_reconfirmation' | 'not_taken' | 'rejected_by_manager'; shift_id?: string | null
}
export interface AvailabilityEntry { id: string; start_at: string; end_at: string; status: string; source: string; editable: boolean }
export interface LeaveRequest { id: string; kind: 'annual' | 'personal' | 'unpaid' | 'other'; start_date: string; end_date: string; reason: string | null; status: 'pending' | 'approved' | 'rejected' | 'cancelled'; decision_note: string | null }
export interface AttendanceSession { id: string; state: string; started_at: string; started_local: string; ended_at: string | null; approval: string; corrected: boolean; worked_minutes: number; break_minutes: number; payable_minutes: number | null; punches: { kind: string; at: string; at_local: string; source: string }[] }
export interface Attendance { timezone: string; current_state: string; sessions: AttendanceSession[]; note: string }
export interface NotificationPrefs {
  push_enabled: boolean; roster_published: boolean; shift_changes: boolean; offers: boolean; reminders: boolean; decisions: boolean
  reminder_lead_minutes: number; lead_choices: number[]; sms_opt_in: boolean; sms_number: string | null; sms_available: boolean; company_push_enabled: boolean
}
export interface InboxItem { id: string; kind: string; title: string; body: string; deep_link: string | null; created_at: string; read: boolean }
export interface LoginResult { status: 'signed_in' | 'mfa_required'; access_token?: string; refresh_token?: string; expires_at?: string; refresh_expires_at?: string; challenge?: string }
export interface WhoAmI { worker_id: string; masked_identity: string; state: 'not_clocked_in' | 'working' | 'on_break'; allowed_actions: string[]; location_mode: string }
export interface PunchResult { state: string; duplicate: boolean; recorded_at?: string; clocked_in_at?: string; clocked_out_at?: string }
