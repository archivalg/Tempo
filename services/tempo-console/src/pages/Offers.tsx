import { useCallback, useEffect, useState } from 'react'
import { ApiError } from '../api/client'
import { cancelOffer, confirmOffer, createOffer, editOffer, listOfferableWorkers, listOffers, rejectOffer, type OfferableWorker, type OfferRow } from '../api/ops'
import { useSite } from '../components/AppShell'
import { HelpLink } from '../components/HelpLink'
import { Banner, Drawer, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { fmtTime } from '../lib/format'
import { utcToZonedInput, zonedToUtcIso } from '../lib/zoned'

const STATUS: Record<OfferRow['status'], ['ok' | 'risk' | 'bad' | 'neutral', string]> = {
  open: ['neutral', 'Open — waiting for answers'], pending_confirmation: ['risk', 'Accepted — needs your confirmation'], filled: ['ok', 'Confirmed — on the roster'], cancelled: ['bad', 'Cancelled'], expired: ['neutral', 'Expired'],
}
const RESP: Record<string, string> = { pending: 'No answer yet', accepted: 'Accepted', declined: 'Declined', needs_reconfirmation: 'Must confirm the change', not_taken: 'Not taken', rejected_by_manager: 'Not confirmed' }

/** Offer an extra shift to chosen employees who use the app. First acceptance holds the shift; you confirm it onto the roster. */
export default function OffersPage() {
  const { site } = useSite()
  const { can } = useTempoContext()
  const tz = site?.timezone ?? 'UTC'
  const [rows, setRows] = useState<OfferRow[] | null>(null)
  const [filter, setFilter] = useState<'active' | 'all'>('active')
  const [open, setOpen] = useState<OfferRow | 'new' | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState('')
  const [people, setPeople] = useState<OfferableWorker[]>([])
  const load = useCallback(() => { if (site) listOffers(site.site_id, filter).then(setRows).catch((e) => setErr(e.message)) }, [site, filter])
  useEffect(() => { setRows(null); load() }, [load])
  useEffect(() => { if (site && can('labour.plan')) listOfferableWorkers(site.site_id).then(setPeople).catch(() => undefined) }, [site, can])
  const label = (id: string) => people.find((p) => p.worker_id === id)?.label ?? `Worker …${id.slice(-4)}`
  async function act(fn: () => Promise<unknown>) { setBusy(true); setErr(null); try { await fn(); setOpen(null); setNote(''); load() } catch (e) { setErr(e instanceof ApiError ? e.message : 'Failed') } finally { setBusy(false) } }
  if (!site) return <Empty title="No site available" />
  const t = (iso: string) => fmtTime(iso, tz, { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
  return (
    <>
      <PageHead title="Shift offers" sub={`${site.name} · extra shifts offered through the Tempo app`}>
        <HelpLink id="offers" />
        {can('labour.plan') && <button className="tp-btn primary" onClick={() => { setOpen('new'); setErr(null) }}>New offer</button>}
        <div className="tp-seg" role="group" aria-label="Filter"><button aria-pressed={filter === 'active'} onClick={() => setFilter('active')}>Active</button><button aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All</button></div>
      </PageHead>
      {err && !open && <Banner tone="bad" title="Problem">{err}</Banner>}
      <section className="tp-card">
        {!rows ? <div className="tp-body"><Skeleton h={140} /></div> : rows.length === 0 ? <Empty title="No offers">Offer a shift to people who have joined the app. They answer on their phone; you confirm.</Empty> : (
          <table className="tp-table"><thead><tr><th>Shift</th><th>Offered to</th><th>Status</th><th /></tr></thead>
            <tbody>{rows.map((o) => (
              <tr key={o.id}>
                <td>{t(o.start_at)} → {fmtTime(o.end_at, tz, { hour: '2-digit', minute: '2-digit', hour12: false })}<div className="tp-muted" style={{ fontSize: 12 }}>{o.role} · {o.zone}</div></td>
                <td>{o.recipients.map((r) => <div key={r.worker_id} style={{ fontSize: 13 }}>{label(r.worker_id)}: <b>{RESP[r.response] ?? r.response}</b></div>)}</td>
                <td><Status tone={STATUS[o.status][0]}>{STATUS[o.status][1]}</Status>{o.auto_confirm && <div className="tp-muted" style={{ fontSize: 12 }}>auto-confirms if no conflict</div>}</td>
                <td><button className="tp-btn" onClick={() => { setOpen(o); setErr(null); setNote('') }}>Manage</button></td>
              </tr>))}</tbody></table>)}
      </section>
      {open === 'new' && <NewOffer tz={tz} siteId={site.site_id} people={people} onClose={() => setOpen(null)} onDone={load} />}
      {open && open !== 'new' && (
        <Drawer title="Manage offer" onClose={() => setOpen(null)}>
          <div className="tp-stack">
            {err && <Banner tone="bad" title="Problem">{err}</Banner>}
            <dl className="tp-dl"><dt>Shift</dt><dd>{t(open.start_at)} → {fmtTime(open.end_at, tz, { hour: '2-digit', minute: '2-digit', hour12: false })}</dd><dt>Role</dt><dd>{open.role} · {open.zone}</dd><dt>Break</dt><dd>{open.break_minutes ?? 'not set'}</dd><dt>Instructions</dt><dd>{open.instructions ?? 'none'}</dd><dt>Status</dt><dd>{STATUS[open.status][1]}</dd></dl>
            {open.status === 'pending_confirmation' && can('labour.plan') && (
              <div className="tp-stack"><Banner tone="info" title={`${label(open.accepted_worker_id ?? '')} accepted`}>Confirming puts the shift on their roster after a final conflict check.</Banner>
                <div className="tp-row"><button className="tp-btn primary" disabled={busy} onClick={() => void act(() => confirmOffer(open.id))}>Confirm onto the roster</button></div>
                <label className="tp-field">Reason if you will not confirm<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
                <button className="tp-btn" disabled={busy || note.trim().length < 3} onClick={() => void act(() => rejectOffer(open.id, note.trim()))}>Do not confirm</button></div>
            )}
            {['open', 'pending_confirmation', 'filled'].includes(open.status) && can('labour.plan') && <EditOffer o={open} tz={tz} busy={busy} onSave={(b) => void act(() => editOffer(open.id, b))} />}
            {['open', 'pending_confirmation', 'filled'].includes(open.status) && can('labour.plan') && (
              <div className="tp-stack"><label className="tp-field">Reason for cancelling (optional)<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
                <button className="tp-btn danger" disabled={busy} onClick={() => void act(() => cancelOffer(open.id, note))}>{open.status === 'filled' ? 'Cancel offer and remove the shift' : 'Cancel offer'}</button></div>
            )}
          </div>
        </Drawer>
      )}
    </>
  )
}

function EditOffer({ o, tz, busy, onSave }: { o: OfferRow; tz: string; busy: boolean; onSave: (b: Partial<{ start_at: string; end_at: string; instructions: string | null }>) => void }) {
  const [f, setF] = useState({ start: utcToZonedInput(o.start_at, tz), end: utcToZonedInput(o.end_at, tz), instructions: o.instructions ?? '' })
  return (
    <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); onSave({ start_at: zonedToUtcIso(f.start, tz), end_at: zonedToUtcIso(f.end, tz), instructions: f.instructions || null }) }}>
      <h3 style={{ margin: '8px 0 0', fontSize: 14 }}>Change this shift</h3>
      <Banner tone="warn" title="Changing a shift clears or re-asks the answer">{o.status === 'filled' ? 'The employee must confirm the new details; the shift stays on their roster, flagged, until they do. If they decline, it is cancelled and you are alerted.' : 'Anyone who accepted is told and must accept again.'}</Banner>
      <div className="tp-cols2"><label className="tp-field">Starts ({tz})<input type="datetime-local" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></label><label className="tp-field">Ends ({tz})<input type="datetime-local" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></label></div>
      <label className="tp-field">Instructions<input value={f.instructions} onChange={(e) => setF({ ...f, instructions: e.target.value })} maxLength={500} /></label>
      <button className="tp-btn" disabled={busy}>Save change</button>
    </form>
  )
}

function NewOffer({ tz, siteId, people, onClose, onDone }: { tz: string; siteId: string; people: OfferableWorker[]; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ role: 'picker', zone: '', start: '', end: '', brk: '30', instructions: '', expires: '', auto: false })
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  async function go() {
    setBusy(true); setErr(null)
    try { await createOffer(siteId, { worker_ids: [...picked], role: f.role.trim(), zone: f.zone.trim(), start_at: zonedToUtcIso(f.start, tz), end_at: zonedToUtcIso(f.end, tz), break_minutes: f.brk ? Number(f.brk) : null, instructions: f.instructions.trim() || null, expires_at: f.expires ? zonedToUtcIso(f.expires, tz) : null, auto_confirm: f.auto }); onDone(); onClose() }
    catch (e) { setErr(e instanceof ApiError ? e.message : 'Failed') } finally { setBusy(false) }
  }
  return (
    <Drawer title="New shift offer" onClose={onClose}>
      <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void go() }}>
        {err && <Banner tone="bad" title="Problem">{err}</Banner>}
        <fieldset className="tp-stack" style={{ border: 0, padding: 0 }}><legend style={{ fontWeight: 600 }}>Offer to (people who have joined the app)</legend>
          {people.length === 0 ? <p className="tp-muted">Nobody at this site has joined the app yet. Invite people in Attendance → Badges &amp; PINs.</p> : people.map((p) => (
            <label key={p.worker_id} className="tp-row"><input type="checkbox" checked={picked.has(p.worker_id)} onChange={(e) => { const n = new Set(picked); if (e.target.checked) n.add(p.worker_id); else n.delete(p.worker_id); setPicked(n) }} /> {p.label}{p.skills.length ? <span className="tp-muted"> — {p.skills.join(', ')}</span> : null}</label>))}
        </fieldset>
        <div className="tp-cols2"><label className="tp-field">Role<input value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })} required /></label><label className="tp-field">Zone<input value={f.zone} onChange={(e) => setF({ ...f, zone: e.target.value })} required /></label></div>
        <div className="tp-cols2"><label className="tp-field">Starts ({tz})<input type="datetime-local" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} required /></label><label className="tp-field">Ends ({tz})<input type="datetime-local" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} required /></label></div>
        <div className="tp-cols2"><label className="tp-field">Break (minutes)<input type="number" min={0} max={180} value={f.brk} onChange={(e) => setF({ ...f, brk: e.target.value })} /></label><label className="tp-field">Answer by (optional)<input type="datetime-local" value={f.expires} onChange={(e) => setF({ ...f, expires: e.target.value })} /></label></div>
        <label className="tp-field">Instructions<input value={f.instructions} onChange={(e) => setF({ ...f, instructions: e.target.value })} maxLength={500} /></label>
        <label className="tp-row"><input type="checkbox" checked={f.auto} onChange={(e) => setF({ ...f, auto: e.target.checked })} /> Confirm automatically when someone accepts and nothing conflicts</label>
        <button className="tp-btn primary" disabled={busy || picked.size === 0 || !f.start || !f.end || !f.zone}>Send offer to {picked.size || 'chosen'} {picked.size === 1 ? 'person' : 'people'}</button>
        <p className="tp-muted" style={{ fontSize: 12 }}>The server checks overlap, rest time and leave for each person when they accept and again when you confirm.</p>
      </form>
    </Drawer>
  )
}
