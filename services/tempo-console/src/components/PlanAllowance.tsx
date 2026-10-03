import { useEffect, useState } from 'react'
import { getMyPlan, type MyPlan } from '../api/ops'
import { HelpLink } from './HelpLink'
import { Banner, Skeleton, Status } from './ui'
import { fmtTime } from '../lib/format'

const SOURCE: Record<string, string> = { manual: 'Recorded by Tempo staff (no card payment)', stripe: 'Card subscription' }

/** The organisation's plan, site count and workforce allowance, with how the worker count is measured. Warnings never block work. */
export function PlanAllowance() {
  const [p, setP] = useState<MyPlan | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { getMyPlan().then(setP).catch((e) => setErr(e.message)) }, [])
  if (err) return <Banner tone="bad" title="Could not load the plan">{err}</Banner>
  if (!p) return <Skeleton h={90} />
  if (!p.managed) return <Banner tone="info" title="No plan recorded">{p.message} {p.active_workers} active worker(s) across {p.sites_in_use} site(s).</Banner>
  const cap = p.worker_allowance
  return (
    <section className="tp-card" aria-label="Plan and allowance"><header><h2>Plan &amp; allowance</h2><HelpLink id="plans" /></header>
      <div className="tp-body tp-stack">
        <dl className="tp-dl">
          <dt>Plan</dt><dd>{p.plan?.name} {p.plan && !p.plan.approved && <Status tone="neutral" title="Prices and inclusions for this plan version have not been approved">Not yet finalised</Status>}</dd>
          <dt>Arrangement</dt><dd>{SOURCE[p.billing_source ?? ''] ?? p.billing_source}{p.manual_kind ? ` · ${p.manual_kind}` : ''}{p.status && p.status !== 'active' ? ` · ${p.status}` : ''}{p.expires_at ? ` · to ${fmtTime(p.expires_at, 'UTC', { day: '2-digit', month: 'short', year: 'numeric' })}` : ''}</dd>
          <dt>Sites</dt><dd>{p.sites_in_use} of {p.licensed_sites}</dd>
          <dt>Active workers</dt><dd>{p.active_workers}{cap ? ` of ${cap}` : ''} <span className="tp-muted">({p.worker_band_label})</span> {p.allowance_state === 'ok' ? <Status tone="ok">Within allowance</Status> : p.allowance_state === 'near' ? <Status tone="risk">Close to allowance</Status> : <Status tone="bad">Over allowance</Status>}</dd>
        </dl>
        {p.allowance_state !== 'ok' && <Banner tone="warn" title={p.allowance_state === 'over' ? 'Over your workforce allowance' : 'Close to your workforce allowance'}>{p.allowance_message}</Banner>}
        <p className="tp-muted" style={{ fontSize: 12 }}>{p.measurement}</p>
      </div>
    </section>
  )
}
