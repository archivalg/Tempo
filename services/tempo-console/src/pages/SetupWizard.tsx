import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getChecklist, getSetupState, putSetupState, setupSite, type Checklist, type SetupState } from '../api/imports'
import { generateRoster } from '../api/ops'
import { ApiError } from '../api/client'
import { HelpLink } from '../components/HelpLink'
import { UploadWizard } from '../components/UploadWizard'
import { Banner, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'

const ZONES = ['Australia/Melbourne', 'Australia/Sydney', 'Australia/Brisbane', 'Australia/Adelaide', 'Australia/Perth', 'Australia/Hobart', 'Australia/Darwin', 'Pacific/Auckland']
const ORDER = ['organisation', 'sites', 'staff', 'standards', 'workload', 'rates', 'attendance', 'roster']
const nextMonday = () => { const d = new Date(); d.setUTCDate(d.getUTCDate() + ((8 - d.getUTCDay()) % 7 || 7)); return d.toISOString().slice(0, 10) }

const COPY: Record<string, { title: string; body: string }> = {
  organisation: { title: 'Your organisation', body: 'This is the organisation Tempo set up for you. Nothing to do here.' },
  sites: { title: 'Your first site', body: 'A site is one warehouse. Its time zone decides what "6am" and "midnight" mean for rosters and attendance, and it cannot be changed later because that would move your history.' },
  staff: { title: 'Your people', body: 'Download the template, fill in one row per person, and upload it. Re-uploading the same file changes nothing. Badge numbers for the kiosk are the worker numbers in this file.' },
  standards: { title: 'How long work takes', body: 'For each activity (picking, packing…), the labour seconds per unit. Workload and rosters depend on these, and they are versioned.' },
  workload: { title: 'Workload', body: 'Load past workload (totals or events) so Tempo can forecast, or a forecast of upcoming work you already have.' },
  rates: { title: 'Labour rates (optional)', body: 'Hourly rates let Tempo show planned cost. Without them cost is shown as unavailable, never as zero. You can skip this and come back.' },
  attendance: { title: 'How people clock in', body: 'Choose now or decide later. You can change this at any time.' },
  roster: { title: 'Your first roster', body: 'Tempo drafts a week from your workload. You review it, someone else approves it, then you publish it.' },
}

/** One resumable path from an empty organisation to a first roster. Which steps are done is read from your data; where you are is remembered for everyone in the organisation. */
export default function SetupWizard() {
  const { access, can } = useTempoContext()
  const [c, setC] = useState<Checklist | null>(null)
  const [st, setSt] = useState<SetupState | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [step, setStep] = useState('sites')
  const load = useCallback(async () => { try { const [a, b] = await Promise.all([getChecklist(), getSetupState()]); setC(a); setSt(b); return b } catch (e) { setErr(e instanceof ApiError ? e.message : 'Could not load setup'); return null } }, [])
  useEffect(() => { void load().then((b) => { if (b && ORDER.includes(b.current_step)) setStep(b.current_step) }) }, [load])
  const go = (k: string) => { setStep(k); void putSetupState({ current_step: k }).catch(() => undefined) }
  if (!c || !st) return err ? <Banner tone="bad" title="Problem">{err}</Banner> : <Skeleton h={300} />
  const byKey = Object.fromEntries(c.steps.map((s) => [s.key, s]))
  const i = ORDER.indexOf(step)
  const cur = byKey[step]
  const isOpt = !!cur?.optional
  const advance = () => go(ORDER[Math.min(i + 1, ORDER.length - 1)])
  return (
    <>
      <PageHead title="Guided setup" sub="Pick up where you left off — on any device. Steps tick off as your data arrives."><HelpLink id="first-setup" /></PageHead>
      {err && <Banner tone="bad" title="Problem">{err}</Banner>}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 240px) 1fr', gap: 16 }}>
        <nav aria-label="Setup steps"><ol style={{ listStyle: 'none', padding: 0, margin: 0, display: 'grid', gap: 6 }}>
          {ORDER.map((k, n) => { const s = byKey[k]; return (
            <li key={k}><button className="tp-btn" style={{ width: '100%', justifyContent: 'space-between', ...(k === step ? { borderColor: 'var(--tp-green)' } : {}) }} aria-current={k === step ? 'step' : undefined} onClick={() => go(k)}>
              <span>{n + 1}. {COPY[k].title.replace(' (optional)', '')}</span><Status tone={s?.state === 'done' ? 'ok' : s?.state === 'skipped' ? 'neutral' : 'risk'}>{s?.state === 'done' ? 'Done' : s?.state === 'skipped' ? 'Skipped' : s?.optional ? 'Optional' : 'To do'}</Status></button></li>) })}
        </ol><p className="tp-muted" style={{ fontSize: 12 }}>{c.done} of {c.total} steps done</p></nav>
        <section className="tp-card" aria-label={COPY[step].title}><header><h2>{COPY[step].title}</h2>{cur?.state === 'done' && <Status tone="ok">Done</Status>}</header>
          <div className="tp-body tp-stack">
            <p style={{ margin: 0 }}>{COPY[step].body}</p>
            {cur?.state === 'done' && <Banner tone="info" title="This step is complete">{cur.detail}</Banner>}
            {step === 'sites' && <SiteStep onDone={() => { void load() }} canConfigure={can('labour.configure')} hints={access?.site_ids ?? []} done={cur?.state === 'done'} />}
            {step === 'staff' && <UploadWizard initial={{ dc: 'master', entity: 'workers' }} onApplied={() => void load()} />}
            {step === 'standards' && <UploadWizard initial={{ dc: 'master', entity: 'work_standards' }} onApplied={() => void load()} />}
            {step === 'workload' && <UploadWizard initial={{ dc: 'bulk', entity: null }} onApplied={() => void load()} />}
            {step === 'rates' && <UploadWizard initial={{ dc: 'master', entity: 'rates' }} onApplied={() => void load()} />}
            {step === 'attendance' && (
              <div className="tp-stack" role="radiogroup" aria-label="Attendance choice">
                {([['tempo_kiosk', 'Use Tempo’s kiosk', 'Workers clock in on a tablet with their badge number and PIN. Create the kiosk in Administration.'], ['external', 'Attendance comes from another system', 'Tempo reads it from your existing time-and-attendance system (needs a connection).'], ['later', 'Decide later', 'Nothing is lost; you can pick at any time.']] as const).map(([k, l, d]) => (
                  <label key={k} className="tp-item" style={{ gridTemplateColumns: 'auto 1fr', cursor: 'pointer' }}><input type="radio" name="att" checked={st.attendance_choice === k} onChange={() => void putSetupState({ attendance_choice: k }).then(() => load())} /><span><span className="t">{l}</span><br /><span className="s">{d}</span></span></label>))}
                {st.attendance_choice === 'tempo_kiosk' && <Link className="tp-btn" style={{ textDecoration: 'none', width: 'fit-content' }} to="/admin">Set up a kiosk</Link>}
              </div>)}
            {step === 'roster' && <RosterStep ready={c.steps.filter((s) => ['sites', 'staff', 'standards', 'workload'].includes(s.key)).every((s) => s.state === 'done')} />}
            <div className="tp-row" style={{ justifyContent: 'space-between', marginTop: 8 }}>
              <button className="tp-btn" disabled={i === 0} onClick={() => go(ORDER[i - 1])}>Back</button>
              <span className="tp-row">
                {isOpt && cur.state === 'todo' && <button className="tp-btn" onClick={() => void putSetupState({ skipped: [...new Set([...st.skipped, step])] }).then(() => { void load(); advance() })}>Skip for now</button>}
                {i < ORDER.length - 1 ? <button className="tp-btn primary" onClick={advance}>{cur?.state === 'done' || cur?.state === 'skipped' ? 'Next' : 'Next (not done yet)'}</button> : <Link className="tp-btn primary" style={{ textDecoration: 'none' }} to="/roster">Open the roster planner</Link>}
              </span>
            </div>
          </div>
        </section>
      </div>
    </>
  )
}

function SiteStep({ onDone, canConfigure, hints, done }: { onDone: () => void; canConfigure: boolean; hints: string[]; done: boolean }) {
  const [f, setF] = useState({ site_id: hints[0] ?? '', name: '', timezone: 'Australia/Melbourne', operating_mode: 'standalone' })
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  if (!canConfigure) return <Banner tone="warn" title="An administrator needs to do this">Adding a site needs the configure permission.</Banner>
  const save = async () => { setBusy(true); setMsg(null); try { const r = await setupSite(f); setMsg({ tone: 'ok', text: r.created ? 'Site added.' : 'Site updated.' }); onDone() } catch (e) { setMsg({ tone: 'bad', text: e instanceof ApiError ? e.message : 'Failed' }) } finally { setBusy(false) } }
  return (
    <form className="tp-stack" style={{ maxWidth: 480 }} onSubmit={(e) => { e.preventDefault(); void save() }}>
      <label className="tp-field">Site ID{hints.length > 0 && <span className="tp-muted" style={{ fontSize: 12 }}> (your administrator reserved: {hints.join(', ')})</span>}<input value={f.site_id} onChange={(e) => setF({ ...f, site_id: e.target.value })} required /></label>
      <label className="tp-field">Name<input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required /></label>
      <label className="tp-field">Time zone<select value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })}>{ZONES.map((z) => <option key={z}>{z}</option>)}</select></label>
      <label className="tp-field">Who runs rosters and attendance?<select value={f.operating_mode} onChange={(e) => setF({ ...f, operating_mode: e.target.value })}><option value="standalone">Tempo (standalone)</option><option value="overlay">Another system (overlay)</option></select></label>
      {msg && <p role="status" style={{ color: msg.tone === 'bad' ? 'var(--tp-red-ink)' : undefined }}>{msg.text}</p>}
      <button className="tp-btn primary" disabled={busy || !f.site_id || !f.name}>{done ? 'Save changes' : 'Add site'}</button>
    </form>
  )
}

function RosterStep({ ready }: { ready: boolean }) {
  const [site, setSite] = useState<string>('')
  const { access } = useTempoContext()
  const [msg, setMsg] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const sid = site || access?.site_ids[0] || ''
  return (
    <div className="tp-stack">
      {!ready && <Banner tone="warn" title="A few steps first">Roster drafting needs a site, people, work standards and workload. Finish those, then come back.</Banner>}
      {(access?.site_ids.length ?? 0) > 1 && <label className="tp-field" style={{ maxWidth: 260 }}>Site<select value={sid} onChange={(e) => setSite(e.target.value)}>{access!.site_ids.map((s) => <option key={s}>{s}</option>)}</select></label>}
      <button className="tp-btn primary" style={{ width: 'fit-content' }} disabled={!ready || busy || !sid} onClick={() => { setBusy(true); setMsg(null); generateRoster(sid, nextMonday()).then(() => setMsg({ tone: 'ok', text: 'Draft created for next week. Open the roster planner to review it.' })).catch((e) => setMsg({ tone: 'bad', text: e instanceof ApiError ? e.message : 'Failed' })).finally(() => setBusy(false)) }}>{busy ? 'Drafting…' : 'Generate a draft for next week'}</button>
      {msg && <p role="status" style={{ color: msg.tone === 'bad' ? 'var(--tp-red-ink)' : undefined }}>{msg.text}</p>}
    </div>
  )
}
