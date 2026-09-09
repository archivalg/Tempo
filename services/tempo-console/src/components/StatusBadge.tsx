const TONE_BY_STATUS: Record<string, string> = {
  completed: 'good',
  confirmed: 'good',
  approved: 'good',
  completed_with_warnings: 'warn',
  partially_confirmed: 'warn',
  validated: 'warn',
  submitted: 'warn',
  unknown: 'warn',
  pending_credentials: 'warn',
  running: 'info',
  queued: 'info',
  accepted: 'info',
  validating: 'info',
  failed: 'bad',
  rejected: 'bad',
  cancelled: 'bad',
  cancel_requested: 'bad',
}

export function StatusBadge({ status }: { status: string }) {
  const tone = TONE_BY_STATUS[status] ?? 'info'
  return <span className={`badge badge-${tone}`}>{status}</span>
}
