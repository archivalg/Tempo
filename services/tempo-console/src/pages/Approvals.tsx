import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { approveRoster, listPendingRosters, publishRoster, rejectRoster, type PendingRoster } from '../api/ops'
import { ApiError } from '../api/client'
import { Banner, Drawer, Empty, PageHead, RosterSteps, Skeleton, Status } from '../components/ui'
import { useSite } from '../components/AppShell'
import { useTempoContext } from '../context/TempoContextProvider'
import { fmtAge, fmtMoney, fmtNum } from '../lib/format'

export default function ApprovalsPage() {
  const { site } = useSite()
  const { can, access } = useTempoContext()
  const [items, setItems] = useState<PendingRoster[] | null>(null)
  const [open, setOpen] = useState<PendingRoster | null>(null)
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(() => { listPendingRosters().then(setItems).catch((e) => setErr(e.message)) }, [])
  useEffect(load, [load])

  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setErr(null)
    try { await fn(); setOpen(null); setNote(''); load() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Failed') } finally { setBusy(false) }
  }
  const d = (a: number | null | undefined, b: number | null | undefined) => (a == null || b == null ? '—' : `${a - b >= 0 ? '+' : ''}${fmtNum(a - b, 1)}`)
  return (
    <>
      <PageHead title="Approvals" sub="Rosters awaiting a decision, with what changes if you approve" />
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      <section className="tp-card">
        <header><h2>Roster approvals</h2><Link to={`/actions${site ? `?site=${site.site_id}` : ''}`}>Vendor writeback actions →</Link></header>
        {!items ? <div className="tp-body"><Skeleton h={100} /></div> : items.length === 0 ? <Empty title="Nothing waiting">No roster is pending approval at your sites.</Empty> : (
          <table className="tp-table">
            <thead><tr><th>Site / week</th><th>Version</th><th>Status</th><th>Waiting</th><th>Hours vs live</th><th /></tr></thead>
            <tbody>{items.map((p) => (
              <tr key={p.id}>
                <td><b>{p.site_name}</b><div className="tp-muted">week of {p.week_start}</div></td>
                <td>v{p.version_no} · {p.source === 'solver' ? 'optimiser' : p.source.replace(/_/g, ' ')}</td>
                <td><RosterSteps state={p.state} /></td>
                <td className="tp-num">{fmtAge(p.age_seconds)}</td>
                <td className="tp-num">{p.impact ? `${fmtNum(p.impact.this_version.hours)} h (${d(p.impact.this_version.hours, p.impact.current_published.hours)})` : '—'}</td>
                <td><button className="tp-btn primary" onClick={() => setOpen(p)}>Review</button></td>
              </tr>))}</tbody>
          </table>
        )}
      </section>

      {open && (
        <Drawer title={`Roster v${open.version_no} — ${open.site_name}`} onClose={() => setOpen(null)}>
          <div className="tp-stack">
            <RosterSteps state={open.state} />
            {open.impact && (
              <table className="tp-table tp-num"><thead><tr><th>Impact</th><th>This version</th><th>Live now</th><th>Change</th></tr></thead><tbody>
                <tr><td>Shifts</td><td>{open.impact.this_version.shifts}</td><td>{open.impact.current_published.shifts}</td><td>{d(open.impact.this_version.shifts, open.impact.current_published.shifts)}</td></tr>
                <tr><td>Workers</td><td>{open.impact.this_version.workers}</td><td>{open.impact.current_published.workers}</td><td>{d(open.impact.this_version.workers, open.impact.current_published.workers)}</td></tr>
                <tr><td>Hours</td><td>{fmtNum(open.impact.this_version.hours)}</td><td>{fmtNum(open.impact.current_published.hours)}</td><td>{d(open.impact.this_version.hours, open.impact.current_published.hours)}</td></tr>
                <tr><td>Agency share</td><td>{open.impact.this_version.agency_share_pct ?? '—'}%</td><td>{open.impact.current_published.agency_share_pct ?? '—'}%</td><td>{d(open.impact.this_version.agency_share_pct, open.impact.current_published.agency_share_pct)}</td></tr>
                {open.impact.this_version.cost !== undefined && <tr><td>Cost</td><td>{fmtMoney(open.impact.this_version.cost)}</td><td>{fmtMoney(open.impact.current_published.cost)}</td><td>{open.impact.this_version.cost != null && open.impact.current_published.cost != null ? fmtMoney(open.impact.this_version.cost - open.impact.current_published.cost) : '—'}</td></tr>}
              </tbody></table>
            )}
            <p>Hard conflicts: {open.impact?.hard_conflicts === 0 ? <Status tone="ok">None</Status> : <Status tone="bad">{open.impact?.hard_conflicts}</Status>}</p>
            <p className="tp-muted" style={{ fontSize: 12.5 }}>Approval binds to payload <code>{open.payload_hash?.slice(0, 12)}…</code>. If the roster changes afterwards the approval is void. <Link to={`/roster?site=${open.site_id}&start=${open.week_start}&v=${open.id}`}>Open on the board →</Link></p>
            {open.submitted_by === access?.user_id && <Banner tone="warn" title="You submitted this roster">A different person must approve it.</Banner>}
            {open.state === 'pending_approval' && can('labour.approve') && open.submitted_by !== access?.user_id && (<>
              <label className="tp-field">Note (required to reject)<textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} /></label>
              <div className="tp-row">
                <button className="tp-btn primary" disabled={busy || (open.impact?.hard_conflicts ?? 0) > 0} onClick={() => void act(() => approveRoster(open.id, note))}>Approve</button>
                <button className="tp-btn danger" disabled={busy || note.trim().length < 3} onClick={() => void act(() => rejectRoster(open.id, note.trim()))}>Reject</button>
              </div>
            </>)}
            {open.state === 'approved' && can('labour.approve') && (
              <div className="tp-stack"><Banner tone="warn" title="Approved — not yet live">Publishing replaces the roster workers currently see for this week.</Banner>
                <button className="tp-btn primary" disabled={busy} onClick={() => void act(() => publishRoster(open.id))}>Publish now</button></div>
            )}
          </div>
        </Drawer>
      )}
    </>
  )
}
