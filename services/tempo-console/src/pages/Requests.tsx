import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { decideLeave, listLeave, type LeaveRow } from '../api/ops'
import { useSite } from '../components/AppShell'
import { HelpLink } from '../components/HelpLink'
import { Banner, Drawer, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'

const TONE = { pending: 'risk', approved: 'ok', rejected: 'bad', cancelled: 'neutral' } as const
const KIND: Record<string, string> = { annual: 'Annual leave', personal: 'Personal / sick', unpaid: 'Unpaid', other: 'Other' }

/** Leave requests from the Tempo app. Approving makes the days a hard roster conflict; the employee is told the decision. */
export default function RequestsPage() {
  const { site } = useSite()
  const { can } = useTempoContext()
  const [status, setStatus] = useState<'pending' | 'approved' | 'all'>('pending')
  const [rows, setRows] = useState<LeaveRow[] | null>(null)
  const [open, setOpen] = useState<LeaveRow | null>(null)
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => { if (site) listLeave(site.site_id, status).then(setRows).catch((e) => setErr(e.message)) }, [site, status])
  useEffect(() => { setRows(null); load() }, [load])
  async function act(approve: boolean) {
    if (!open) return
    setBusy(true); setErr(null)
    try { await decideLeave(open.id, approve, note); setOpen(null); setNote(''); load() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Failed') } finally { setBusy(false) }
  }
  if (!site) return <Empty title="No site available" />
  return (
    <>
      <PageHead title="Leave requests" sub={`${site.name} · requests sent from the Tempo app`}>
        <HelpLink id="leave-requests" />
        <div className="tp-seg" role="group" aria-label="Filter">{(['pending', 'approved', 'all'] as const).map((k) => <button key={k} aria-pressed={status === k} onClick={() => setStatus(k)}>{k === 'pending' ? 'Waiting' : k === 'approved' ? 'Approved' : 'All'}</button>)}</div>
      </PageHead>
      {err && !open && <Banner tone="bad" title="Problem">{err}</Banner>}
      <section className="tp-card">
        {!rows ? <div className="tp-body"><Skeleton h={120} /></div> : rows.length === 0 ? <Empty title="No requests">Leave requested in the app appears here for a decision.</Empty> : (
          <table className="tp-table"><thead><tr><th>Employee</th><th>Kind</th><th>Days</th><th>Rostered in that time</th><th>Status</th><th /></tr></thead>
            <tbody>{rows.map((r) => (
              <tr key={r.id}><td>{r.label}</td><td>{KIND[r.kind] ?? r.kind}</td><td>{r.start_date} → {r.end_date}</td>
                <td>{r.affected_shifts > 0 ? <Status tone="risk">{r.affected_shifts} shift{r.affected_shifts === 1 ? '' : 's'}</Status> : <span className="tp-muted">none</span>}</td>
                <td><Status tone={TONE[r.status]}>{r.status}</Status></td>
                <td>{r.status === 'pending' && can('labour.approve') && <button className="tp-btn" onClick={() => { setOpen(r); setNote(''); setErr(null) }}>Decide</button>}</td></tr>))}</tbody></table>)}
      </section>
      {open && (
        <Drawer title={`Leave — ${open.label}`} onClose={() => setOpen(null)}>
          <div className="tp-stack">
            {err && <Banner tone="bad" title="Problem">{err}</Banner>}
            <dl className="tp-dl"><dt>Kind</dt><dd>{KIND[open.kind]}</dd><dt>Days</dt><dd>{open.start_date} → {open.end_date}</dd><dt>Reason</dt><dd>{open.reason ?? '—'}</dd></dl>
            {open.affected_shifts > 0 && <Banner tone="warn" title={`${open.affected_shifts} rostered shift(s) fall in these days`}>Approving does not remove them. They become hard conflicts the next time the roster is checked; reassign them.</Banner>}
            <label className="tp-field">Note to the employee (required to decline)<input value={note} onChange={(e) => setNote(e.target.value)} maxLength={300} /></label>
            <div className="tp-row"><button className="tp-btn primary" disabled={busy} onClick={() => void act(true)}>Approve</button><button className="tp-btn danger" disabled={busy || note.trim().length < 3} onClick={() => void act(false)}>Decline</button></div>
          </div>
        </Drawer>
      )}
    </>
  )
}
