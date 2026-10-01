import { useEffect, useRef, useState } from 'react'
import { applyBatch, downloadRejected, downloadTemplate, getContracts, inspectCsv, stageCsv, undoBatch, type Batch, type ContractDef, type Inspect } from '../api/imports'
import { Banner, Status } from './ui'
import { fmtNum } from '../lib/format'

const key = (c: ContractDef) => `${c.data_class}|${c.entity ?? ''}`
const ORDER = ['master|workers', 'master|work_standards', 'forecast|', 'bulk|', 'transactions|']
const HINT: Record<string, string> = {
  'master|workers': 'Start here: who works for you.', 'master|work_standards': 'Needed before any workload can name an activity.', 'forecast|': 'What you expect to be processed.',
  'bulk|': 'Daily or hourly totals of what was processed.', 'transactions|': 'One row per event, when your system can send them.',
}

export function UploadWizard({ initial }: { initial?: { dc: string; entity: string | null } }) {
  const [contracts, setContracts] = useState<ContractDef[]>([])
  const [sel, setSel] = useState<ContractDef | null>(null)
  const [file, setFile] = useState<{ name: string; data: ArrayBuffer } | null>(null)
  const [insp, setInsp] = useState<Inspect | null>(null)
  const [mapping, setMapping] = useState<Record<string, string | null>>({})
  const [opts, setOpts] = useState<Record<string, string>>({})
  const [save, setSave] = useState(true)
  const [batch, setBatch] = useState<Batch | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    getContracts().then((r) => {
      const sorted = [...r.contracts].sort((a, b) => ORDER.indexOf(key(a)) - ORDER.indexOf(key(b)))
      setContracts(sorted)
      if (initial) setSel(sorted.find((c) => c.data_class === initial.dc && (c.entity ?? null) === (initial.entity ?? null)) ?? null)
    }).catch((e) => setErr(e.message))
  }, [initial])

  const reset = () => { setFile(null); setInsp(null); setBatch(null); setErr(null); if (inputRef.current) inputRef.current.value = '' }
  const run = async (fn: () => Promise<void>) => { setBusy(true); setErr(null); try { await fn() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) } }

  async function choose(f: File | undefined) {
    if (!f || !sel) return
    await run(async () => {
      const data = await f.arrayBuffer()
      const i = await inspectCsv(sel.data_class, sel.entity, data)
      setFile({ name: f.name, data }); setInsp(i); setMapping(i.suggested_mapping); setBatch(null)
    })
  }
  const missing = sel?.fields.filter((f) => f.required && !mapping[f.name]).map((f) => f.name) ?? []
  const optMissing = sel?.batch_options.filter((o) => o.required && !(opts[o.name] ?? (o.type === 'enum' ? o.choices?.[0] : ''))).map((o) => o.name) ?? []

  const check = () => run(async () => {
    if (!sel || !file) return
    const o: Record<string, string> = { ...opts }
    sel.batch_options.forEach((b) => { if (b.type === 'enum' && !o[b.name]) o[b.name] = b.choices?.[0] ?? '' })
    setBatch(await stageCsv(sel.data_class, sel.entity, file.data, mapping, o, file.name, save))
  })
  const apply = (partial: boolean) => run(async () => { if (batch) setBatch(await applyBatch(batch.id, partial)) })
  const undo = () => run(async () => { if (batch) setBatch(await undoBatch(batch.id)) })

  return (
    <div className="tp-stack">
      <section className="tp-card" aria-label="Step 1 — what are you loading"><header><h2>1. What are you loading?</h2></header>
        <div className="tp-body tp-row" style={{ flexWrap: 'wrap', gap: 8 }}>
          {contracts.map((c) => (
            <button key={key(c)} className="tp-btn" aria-pressed={sel === c} style={sel === c ? { borderColor: 'var(--tp-green)', background: 'var(--tp-green-bg)' } : undefined} onClick={() => { setSel(c); reset(); setOpts({}) }}>
              <strong>{c.title.replace(/ \(.*\)$/, '')}</strong><br /><span className="tp-muted" style={{ fontSize: 12 }}>{HINT[key(c)]}</span></button>))}
        </div>
        {sel && <div className="tp-body tp-stack"><p style={{ margin: 0 }}>{sel.purpose}</p>
          <div className="tp-row"><button className="tp-btn" onClick={() => void run(() => downloadTemplate(sel.data_class, sel.entity))}>⭳ Download the template</button>
            <span className="tp-muted" style={{ fontSize: 12.5 }}>Up to {fmtNum(sel.limits.max_rows_per_batch)} rows per file. Your own column names are fine — you map them next.</span></div>
          <details><summary>What each column means</summary>
            <table className="tp-table"><thead><tr><th>Column</th><th>Needed?</th><th>Meaning</th><th>Example</th></tr></thead><tbody>
              {sel.fields.map((f) => <tr key={f.name}><td><code>{f.name}</code></td><td>{f.required ? 'Yes' : 'Optional'}</td><td>{f.description}</td><td><code>{f.example}</code></td></tr>)}</tbody></table>
            {sel.notes.map((n) => <p key={n} className="tp-muted" style={{ fontSize: 12.5 }}>{n}</p>)}</details></div>}
      </section>

      {sel && (
        <section className="tp-card" aria-label="Step 2 — choose the file"><header><h2>2. Choose your file</h2></header>
          <div className="tp-body tp-stack">
            <label className="tp-field">CSV file<input ref={inputRef} type="file" accept=".csv,text/csv" onChange={(e) => void choose(e.target.files?.[0])} /></label>
            {err && <Banner tone="bad" title="That file could not be used">{err}</Banner>}
            {insp && file && (<>
              <p style={{ margin: 0 }}><strong>{file.name}</strong> — {fmtNum(insp.row_count)} rows. {insp.used_saved_mapping ? 'Your saved column choices were applied.' : 'Columns were matched by name; check them below.'}</p>
              <table className="tp-table" aria-label="Column mapping"><thead><tr><th>Tempo needs</th><th>Your column</th><th>First value</th></tr></thead><tbody>
                {sel.fields.map((f) => (
                  <tr key={f.name}><td><code>{f.name}</code>{f.required ? <span className="tp-muted"> (required)</span> : null}</td>
                    <td><select aria-label={`Column for ${f.name}`} value={mapping[f.name] ?? ''} onChange={(e) => setMapping({ ...mapping, [f.name]: e.target.value || null })}>
                      <option value="">{f.required ? '— choose a column —' : '— not in my file —'}</option>{insp.headers.map((h) => <option key={h}>{h}</option>)}</select></td>
                    <td className="tp-muted">{mapping[f.name] ? insp.sample[0]?.[mapping[f.name]!] : ''}</td></tr>))}</tbody></table>
              {sel.batch_options.length > 0 && (
                <div className="tp-stack" aria-label="Options">{sel.batch_options.filter((o) => !(o.name.startsWith('slice_') && (opts.mode ?? 'upsert') !== 'replace_slice')).map((o) => (
                  <label key={o.name} className="tp-field">{o.name.replace(/_/g, ' ')}{o.required ? ' (required)' : ''}
                    {o.type === 'enum' ? <select value={opts[o.name] ?? o.choices?.[0]} onChange={(e) => setOpts({ ...opts, [o.name]: e.target.value })}>{o.choices?.map((c) => <option key={c}>{c}</option>)}</select>
                      : o.type === 'bool' ? <select value={opts[o.name] ?? 'false'} onChange={(e) => setOpts({ ...opts, [o.name]: e.target.value })}><option value="false">No</option><option value="true">Yes — replace workload from other sources</option></select>
                        : <input type={o.type === 'date' ? 'date' : 'text'} value={opts[o.name] ?? ''} placeholder={o.example} onChange={(e) => setOpts({ ...opts, [o.name]: e.target.value })} />}
                    <span className="tp-muted" style={{ fontSize: 12 }}>{o.description}</span></label>))}</div>)}
              <label className="tp-row" style={{ gap: 8 }}><input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} /> Remember these column choices next time</label>
              <div className="tp-row"><button className="tp-btn primary" disabled={busy || missing.length > 0 || optMissing.length > 0} onClick={() => void check()}>{busy ? 'Checking…' : 'Check the file'}</button>
                {(missing.length > 0 || optMissing.length > 0) && <span className="tp-muted">Still needed: {[...missing, ...optMissing].join(', ')}</span>}</div>
            </>)}
          </div>
        </section>)}

      {batch && <Result batch={batch} busy={busy} onApply={apply} onUndo={undo} onAgain={reset} />}
    </div>
  )
}

export function Result({ batch, busy, onApply, onUndo, onAgain }: { batch: Batch; busy: boolean; onApply?: (partial: boolean) => void; onUndo?: () => void; onAgain?: () => void }) {
  const s = batch.summary
  const accepted = batch.ok_rows + batch.warning_rows
  const applied = batch.state === 'applied'
  return (
    <section className="tp-card" aria-label="Check result"><header><h2>{applied ? 'Loaded' : batch.state === 'undone' ? 'Undone' : '3. What will happen'}</h2>
      <Status tone={applied ? 'ok' : batch.state === 'undone' ? 'neutral' : batch.error_rows || s.blocking?.length ? 'risk' : 'ok'}>{batch.state}</Status></header>
      <div className="tp-body tp-stack">
        {batch.replayed && <Banner tone="info" title="You have already sent this exact file">Nothing new was recorded, so nothing can be counted twice. {applied ? 'It was applied earlier.' : ''}</Banner>}
        <dl className="tp-dl" style={{ gridTemplateColumns: '170px 1fr' }}>
          <dt>Rows in the file</dt><dd>{fmtNum(batch.total_rows)}</dd>
          <dt>Accepted</dt><dd>{fmtNum(accepted)}{batch.warning_rows ? ` (${batch.warning_rows} with a note)` : ''}</dd>
          <dt>Rejected</dt><dd>{batch.error_rows ? <Status tone="bad">{fmtNum(batch.error_rows)} {batch.error_rows === 1 ? 'row' : 'rows'}</Status> : 'None'}</dd>
          {s.creates != null && <><dt>New</dt><dd>{fmtNum(s.creates)}</dd></>}
          {s.updates != null && s.updates > 0 && <><dt>Changed</dt><dd>{fmtNum(s.updates)}</dd></>}
          {s.unchanged != null && s.unchanged > 0 && <><dt>Already up to date</dt><dd>{fmtNum(s.unchanged)}</dd></>}
          {s.total_units != null && <><dt>Total units</dt><dd>{fmtNum(s.total_units, 1)}</dd></>}
        </dl>
        {s.blocking?.map((b) => <Banner key={b} tone="bad" title="This is on hold">{b}</Banner>)}
        {s.notes?.map((n) => <Banner key={n} tone="warn" title="Please note">{n}</Banner>)}
        {(s.incomplete_periods ?? 0) > 0 && <p className="tp-muted">{s.incomplete_periods} day(s) in the replaced range have no value, e.g. {s.incomplete_sample?.slice(0, 3).join('; ')}.</p>}
        {batch.rejected_sample && batch.rejected_sample.length > 0 && (
          <div><h3 style={{ marginBottom: 6 }}>Rejected rows{batch.error_rows > batch.rejected_sample.length ? ` (first ${batch.rejected_sample.length} of ${batch.error_rows})` : ''}</h3>
            <table className="tp-table" aria-label="Rejected rows"><thead><tr><th>Row</th><th>Why</th></tr></thead><tbody>
              {batch.rejected_sample.map((r) => <tr key={r.row}><td>{r.row}</td><td>{r.messages.filter((m) => m.level === 'error').map((m) => m.text).join(' · ')}</td></tr>)}</tbody></table>
            <button className="tp-btn" onClick={() => void downloadRejected(batch.id)}>⭳ Download rejected rows to fix</button></div>)}
        {applied && s.applied && <p style={{ margin: 0 }}>Done. {s.applied_partial ? 'Only the accepted rows were loaded; the rejected rows were not.' : ''}</p>}
        <div className="tp-row">
          {batch.state === 'validated' && onApply && <>
            <button className="tp-btn primary" disabled={busy || !batch.can_apply || batch.error_rows > 0} onClick={() => onApply(false)}>Load {fmtNum(accepted)} rows</button>
            {batch.error_rows > 0 && accepted > 0 && !s.blocking?.length && <button className="tp-btn" disabled={busy} onClick={() => onApply(true)}>Load only the {fmtNum(accepted)} accepted rows</button>}</>}
          {applied && batch.can_undo && onUndo && <button className="tp-btn" disabled={busy} onClick={onUndo}>Undo this load</button>}
          {onAgain && <button className="tp-btn" onClick={onAgain}>{applied ? 'Load another file' : 'Start again'}</button>}
        </div>
      </div>
    </section>
  )
}
