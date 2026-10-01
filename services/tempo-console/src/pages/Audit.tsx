import { useCallback, useEffect, useState } from 'react'
import { getAudit, type AuditItem, type AuditPage } from '../api/ops'
import { useSite } from '../components/AppShell'
import { Banner, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { fmtTime } from '../lib/format'

const tone = (d: string) => (d === 'allowed' || d === 'applied' ? 'ok' : d === 'denied' ? 'bad' : 'neutral') as 'ok' | 'bad' | 'neutral'

export default function AuditPage() {
  const { site } = useSite()
  const tz = site?.timezone ?? 'UTC'
  const [action, setAction] = useState('')
  const [decision, setDecision] = useState('')
  const [rows, setRows] = useState<AuditItem[] | null>(null)
  const [actions, setActions] = useState<string[]>([])
  const [next, setNext] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (before?: string) => {
    setBusy(true); setErr(null)
    try {
      const p: AuditPage = await getAudit({ action: action || undefined, decision: decision || undefined, before })
      setRows((prev) => (before && prev ? [...prev, ...p.items] : p.items)); setNext(p.next_before); setActions(p.actions)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }, [action, decision])
  useEffect(() => { setRows(null); void load() }, [load])

  return (
    <>
      <PageHead title="Audit log" sub="Who did what in this organisation, newest first. Read-only; passwords, tokens and PINs are never recorded.">
        <label className="tp-field">Action<select value={action} onChange={(e) => setAction(e.target.value)}><option value="">All actions</option>{actions.map((a) => <option key={a}>{a}</option>)}</select></label>
        <label className="tp-field">Outcome<select value={decision} onChange={(e) => setDecision(e.target.value)}><option value="">Any</option><option value="allowed">Allowed</option><option value="denied">Denied</option></select></label>
      </PageHead>
      {err && <Banner tone="bad" title="Could not load the audit log">{err}</Banner>}
      <section className="tp-card" aria-label="Audit events">
        {!rows ? <div className="tp-body"><Skeleton h={240} /></div> : rows.length === 0 ? <Empty title="No matching events" /> : (
          <div style={{ overflow: 'auto' }}><table className="tp-table">
            <thead><tr><th>When ({tz})</th><th>Who</th><th>Action</th><th>Outcome</th><th>Detail</th></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.event_id}><td className="tp-num">{fmtTime(r.at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}</td>
                <td>{r.actor_name ?? r.actor_id}<div className="tp-muted" style={{ fontSize: 11 }}>{r.actor_type}</div></td>
                <td><code>{r.action}</code></td><td><Status tone={tone(r.decision)}>{r.decision}</Status></td>
                <td className="tp-muted" style={{ fontSize: 12 }}>{[r.reason_code, r.ref].filter(Boolean).join(' · ') || '—'}</td></tr>))}</tbody>
          </table></div>)}
        {next && <div className="tp-body"><button className="tp-btn" disabled={busy} onClick={() => void load(next)}>{busy ? 'Loading…' : 'Load older events'}</button></div>}
      </section>
    </>
  )
}
