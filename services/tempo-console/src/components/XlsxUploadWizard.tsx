import { useRef, useState } from 'react'
import { inspectXlsx, stageXlsx, type XlsxInspect, type XlsxStageResult } from '../api/xlsx'
import { Banner, Status } from './ui'
import { fmtNum } from '../lib/format'

/** Workbook (.xlsx) upload — the API-only counterpart of the CSV UploadWizard above. A workbook can
 * carry several master-data sheets at once (Workers, Work Standards, Orders, ...); each recognised
 * sheet is staged AND applied together, in one atomic pass — either every sheet's rows are loaded, or
 * (on any failure) none of them are. There is no separate "preview, then click apply" step for the
 * whole workbook the way a single CSV file has, because applying one sheet at a time would let a
 * LATER sheet's failure leave an EARLIER sheet's rows behind — exactly what atomic apply prevents.
 * Source-workbook compatibility with Arch's actual supplied v1/v2 files is unverified; this reads the
 * structural layout (header row, metadata/example rows, data start row) and the v1/v2 field names
 * this programme was told to expect — see docs/order-driven-planning.md. */
export function XlsxUploadWizard() {
  const [file, setFile] = useState<{ name: string; data: ArrayBuffer } | null>(null)
  const [insp, setInsp] = useState<XlsxInspect | null>(null)
  const [result, setResult] = useState<XlsxStageResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    setErr(null)
    try {
      await fn()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function choose(f: File | undefined) {
    if (!f) return
    await run(async () => {
      const data = await f.arrayBuffer()
      setFile({ name: f.name, data })
      setResult(null)
      setInsp(await inspectXlsx(data))
    })
  }

  const load = () =>
    run(async () => {
      if (!file) return
      setResult(await stageXlsx(file.data, file.name))
    })

  const reset = () => {
    setFile(null)
    setInsp(null)
    setResult(null)
    setErr(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  const recognisedCount = insp?.sheets.filter((s) => s.recognised).length ?? 0
  const unrecognised = insp?.sheets.filter((s) => !s.recognised) ?? []

  return (
    <div className="tp-stack">
      <section className="tp-card" aria-label="Workbook upload">
        <header>
          <h2>Upload a workbook (.xlsx)</h2>
        </header>
        <div className="tp-body tp-stack">
          <p style={{ margin: 0 }} className="tp-muted">
            One file can carry several sheets (Workers, Work Standards, Process templates/steps, Orders, rates, shifts and more). Each sheet's own tab name says what it loads —
            this is checked before anything is loaded. Every recognised sheet is loaded together, in one pass: if any sheet has a problem, nothing from the file is loaded.
          </p>
          <label className="tp-field">
            Workbook file
            <input ref={inputRef} type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(e) => void choose(e.target.files?.[0])} />
          </label>
          {err && (
            <Banner tone="bad" title="That workbook could not be used">
              {err}
            </Banner>
          )}

          {insp && file && (
            <>
              <p style={{ margin: 0 }}>
                <strong>{file.name}</strong> — {insp.sheets.length} sheet{insp.sheets.length === 1 ? '' : 's'}, {recognisedCount} recognised.
              </p>
              <table className="tp-table" aria-label="Sheets found">
                <thead>
                  <tr>
                    <th>Sheet</th>
                    <th>Loads into</th>
                    <th>Rows</th>
                    <th>Required columns still needed</th>
                  </tr>
                </thead>
                <tbody>
                  {insp.sheets.map((s) => (
                    <tr key={s.sheet}>
                      <td>{s.sheet}</td>
                      <td>{s.recognised ? <code>{s.entity}</code> : <Status tone="risk">not recognised — will be skipped</Status>}</td>
                      <td>{fmtNum(s.row_count)}</td>
                      <td>{s.missing_required && s.missing_required.length > 0 ? <Status tone="bad">{s.missing_required.join(', ')}</Status> : s.recognised ? 'None' : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {unrecognised.length > 0 && (
                <Banner tone="warn" title="Some sheet names were not recognised">
                  {unrecognised.map((s) => s.sheet).join(', ')} will be skipped — rename the tab to match a known entity (Workers, Work Standards, Orders, ...) if this was meant to load.
                </Banner>
              )}
              <div className="tp-row">
                <button className="tp-btn primary" disabled={busy || recognisedCount === 0} onClick={() => void load()}>
                  {busy ? 'Loading…' : `Load ${recognisedCount} sheet${recognisedCount === 1 ? '' : 's'}`}
                </button>
              </div>
            </>
          )}
        </div>
      </section>

      {result && <XlsxResult result={result} onAgain={reset} />}
    </div>
  )
}

function XlsxResult({ result, onAgain }: { result: XlsxStageResult; onAgain: () => void }) {
  // Reaching this component at all means the whole workbook loaded successfully — the apply is
  // all-or-nothing (app/api/v1/imports.py::stage_xlsx), so any sheet's genuine failure is reported as
  // an error banner instead (see the Banner above, from the thrown request error), never as a mixed
  // per-sheet result here. The only per-sheet "note" case that CAN appear in a successful response is
  // a sheet with no data rows at all — harmless, not a failure.
  const loaded = result.applied.filter((s) => s.batch)
  return (
    <section className="tp-card" aria-label="Workbook load result">
      <header>
        <h2>Workbook loaded</h2>
        <Status tone="ok">loaded</Status>
      </header>
      <div className="tp-body tp-stack">
        <table className="tp-table" aria-label="Per-sheet result">
          <thead>
            <tr>
              <th>Sheet</th>
              <th>Loads into</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {result.applied.map((s) => (
              <tr key={s.sheet}>
                <td>{s.sheet}</td>
                <td>
                  <code>{s.entity}</code>
                </td>
                <td>
                  {s.batch ? (
                    <span>
                      {fmtNum((s.batch.summary.creates ?? 0) + (s.batch.summary.updates ?? 0))} row{(s.batch.summary.creates ?? 0) + (s.batch.summary.updates ?? 0) === 1 ? '' : 's'} loaded
                    </span>
                  ) : (
                    <Status tone="bad">{s.note}</Status>
                  )}
                </td>
              </tr>
            ))}
            {result.skipped_sheets.map((name) => (
              <tr key={name}>
                <td>{name}</td>
                <td className="tp-muted">—</td>
                <td className="tp-muted">Not a recognised sheet name — skipped</td>
              </tr>
            ))}
          </tbody>
        </table>
        {loaded.length > 0 && <p style={{ margin: 0 }}>Done. All {loaded.length} recognised sheet{loaded.length === 1 ? '' : 's'} were loaded together.</p>}
        <div className="tp-row">
          <button className="tp-btn" onClick={onAgain}>
            Load another workbook
          </button>
        </div>
      </div>
    </section>
  )
}
