import { useCallback, useEffect, useState } from 'react'
import { confirmHandoff, downloadHandoff, listHandoffs, submitHandoff, type Handoff } from '../api/ops'
import { Status, type Tone } from './ui'

const LABEL: Record<Handoff['state'], [Tone, string]> = {
  pending: ['risk', 'Not handed over yet'], exported: ['risk', 'File downloaded — waiting for someone to load it'], confirmed_by_operator: ['ok', 'Loaded — confirmed by a person (not by the vendor)'],
  submitted: ['risk', 'Sent — waiting for the vendor'], vendor_confirmed: ['ok', 'Confirmed by the vendor'], unconfirmed: ['risk', 'Sent, but the vendor outcome is unknown'],
  rejected: ['bad', 'Rejected by the vendor'], superseded: ['neutral', 'Replaced by a newer publish'],
}

/** Overlay sites keep their roster of record in another system. Tempo hands it over and says plainly what has and has not been confirmed. */
export function HandoffCard({ site, versionId, canAct }: { site: string; versionId: string; canAct: boolean }) {
  const [h, setH] = useState<Handoff | null | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [ref, setRef] = useState('')
  const [note, setNote] = useState('')
  const load = useCallback(() => { listHandoffs(site, versionId).then((r) => setH(r[0] ?? null)).catch((e) => setErr(e.message)) }, [site, versionId])
  useEffect(() => { setH(undefined); load() }, [load])
  const act = async (fn: () => Promise<unknown>) => { setBusy(true); setErr(null); try { await fn() } catch (e) { setErr((e as Error).message) } finally { setBusy(false); load() } }
  if (h === undefined) return null
  if (h === null) return null
  const [tone, label] = LABEL[h.state]
  return (
    <section className="tp-card" aria-label="Hand-over to the external system"><header><h2>Hand-over to the external system</h2></header>
      <div className="tp-body tp-stack">
        <div><Status tone={tone}>{label}</Status></div>
        <p className="tp-muted" style={{ margin: 0, fontSize: 12.5 }}>This site’s roster of record is outside Tempo. {h.shifts} shifts need to reach it. Tempo only calls something “confirmed by the vendor” when the vendor’s connector says so.</p>
        {h.confirmed_at && <p style={{ margin: 0 }}>{h.confirmation_kind === 'vendor' ? 'Vendor confirmation' : 'Attested'} at {new Date(h.confirmed_at).toLocaleString()}{h.confirm_reference ? ` · reference ${h.confirm_reference}` : ''}{h.confirm_note ? ` · ${h.confirm_note}` : ''}</p>}
        {h.vendor_detail && <p className="tp-muted" style={{ margin: 0, fontSize: 12.5 }}>Vendor: {h.vendor_detail}</p>}
        {err && <p role="alert" className="tp-badge bad" style={{ whiteSpace: 'normal', display: 'block' }}>✕ {err}</p>}
        {canAct && ['pending', 'exported', 'unconfirmed', 'rejected'].includes(h.state) && (
          <div className="tp-row">
            <button className="tp-btn" disabled={busy} onClick={() => void act(() => downloadHandoff(h.id))}>⭳ Download roster file</button>
            <button className="tp-btn" disabled={busy} onClick={() => void act(() => submitHandoff(h.id))}>Send to vendor</button>
          </div>)}
        {canAct && h.state === 'exported' && (
          <form className="tp-stack" onSubmit={(e) => { e.preventDefault(); void act(() => confirmHandoff(h.id, ref, note)) }} aria-label="Confirm the file was loaded">
            <label className="tp-field">Reference in the other system (import batch or roster id)<input value={ref} onChange={(e) => setRef(e.target.value)} required /></label>
            <label className="tp-field">Note (optional)<input value={note} onChange={(e) => setNote(e.target.value)} /></label>
            <button className="tp-btn primary" disabled={busy || ref.trim().length < 2} type="submit">I loaded this file — record it</button>
          </form>)}
      </div>
    </section>
  )
}
