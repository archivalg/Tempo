const TONE_BY_STATUS: Record<string, string> = {
  completed: 'ok',
  confirmed: 'ok',
  approved: 'ok',
  completed_with_warnings: 'risk',
  partially_confirmed: 'risk',
  validated: 'risk',
  submitted: 'risk',
  unknown: 'risk',
  pending_credentials: 'risk',
  running: 'neutral',
  queued: 'neutral',
  accepted: 'neutral',
  validating: 'neutral',
  failed: 'bad',
  rejected: 'bad',
  cancelled: 'bad',
  cancel_requested: 'bad',
}

export function StatusBadge({ status }: { status: string }) {
  const tone = TONE_BY_STATUS[status] ?? 'neutral'
  const icon = tone === 'ok' ? '✓' : tone === 'risk' ? '▲' : tone === 'bad' ? '✕' : '●'
  return <span className={`tp-badge ${tone}`}><span aria-hidden="true">{icon}</span>{status.replace(/_/g, ' ')}</span>
}
