import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  createCredential, getDataStatus, getBatch, listBatches, listCredentials, revokeCredential, rotateCredential, setForecastSource, undoBatch, applyBatch, downloadTemplate,
  type Batch, type Credential, type DataStatus,
} from '../api/imports'
import { useSite } from '../components/AppShell'
import { SetupChecklist } from '../components/SetupChecklist'
import { Result, UploadWizard } from '../components/UploadWizard'
import { Banner, Drawer, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { fmtTime } from '../lib/format'

const TABS = [['start', 'Getting started'], ['upload', 'Load data'], ['history', 'History'], ['status', 'What data we have'], ['api', 'API']] as const
type Tab = (typeof TABS)[number][0]

export default function DataPage() {
  const [params, setParams] = useSearchParams()
  const tab = (params.get('tab') as Tab) || 'start'
  const go = (t: Tab) => { const p = new URLSearchParams(params); p.set('tab', t); setParams(p, { replace: true }) }
  const initial = params.get('class') ? { dc: params.get('class')!, entity: params.get('entity') } : undefined
  return (
    <>
      <PageHead title="Data" sub="Bring in your staff, work standards, forecasts and workload — by spreadsheet or by API. Nothing changes until you confirm." />
      <div className="tp-seg" role="tablist" aria-label="Data sections" style={{ marginBottom: 12 }}>
        {TABS.map(([k, label]) => <button key={k} role="tab" aria-selected={tab === k} aria-pressed={tab === k} onClick={() => go(k)}>{label}</button>)}
      </div>
      {tab === 'start' && <SetupChecklist />}
      {tab === 'upload' && <UploadWizard key={`${initial?.dc}${initial?.entity}`} initial={initial} />}
      {tab === 'history' && <History />}
      {tab === 'status' && <StatusTab />}
      {tab === 'api' && <ApiTab />}
    </>
  )
}

function History() {
  const [rows, setRows] = useState<Batch[] | null>(null)
  const [open, setOpen] = useState<Batch | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const { site } = useSite()
  const tz = site?.timezone ?? 'UTC'
  const load = useCallback(() => { listBatches().then(setRows).catch((e) => setErr(e.message)) }, [])
  useEffect(load, [load])
  const act = async (fn: () => Promise<Batch>) => { setBusy(true); setErr(null); try { setOpen(await fn()); load() } catch (e) { setErr((e as Error).message) } finally { setBusy(false) } }
  return (
    <section className="tp-card" aria-label="Load history"><header><h2>Everything that has been loaded</h2></header>
      {err && <div className="tp-body"><Banner tone="bad" title="Problem">{err}</Banner></div>}
      {!rows ? <div className="tp-body"><Skeleton h={160} /></div> : rows.length === 0 ? <Empty title="Nothing has been loaded yet">Use “Load data” to start.</Empty> : (
        <table className="tp-table"><thead><tr><th>When ({tz})</th><th>What</th><th>How</th><th>Rows</th><th>Rejected</th><th>State</th><th /></tr></thead><tbody>
          {rows.map((b) => (
            <tr key={b.id}><td>{fmtTime(b.created_at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}</td>
              <td>{b.data_class}{b.entity ? ` · ${b.entity.replace('_', ' ')}` : ''}<div className="tp-muted" style={{ fontSize: 11 }}>{b.source_label}</div></td><td>{b.channel === 'csv' ? 'Spreadsheet' : 'API'}</td>
              <td>{b.total_rows}</td><td>{b.error_rows || '—'}</td>
              <td><Status tone={b.state === 'applied' ? 'ok' : b.state === 'validated' ? 'risk' : 'neutral'}>{b.state === 'validated' ? 'waiting' : b.state}</Status></td>
              <td><button className="tp-btn" onClick={() => void getBatch(b.id).then(setOpen)}>Open</button></td></tr>))}</tbody></table>)}
      {open && <Drawer title={`Load ${open.id.slice(-6)}`} onClose={() => setOpen(null)}>
        <Result batch={open} busy={busy} onApply={(p) => void act(() => applyBatch(open.id, p))} onUndo={() => void act(() => undoBatch(open.id))} /></Drawer>}
    </section>
  )
}

function StatusTab() {
  const [s, setS] = useState<DataStatus | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const { site } = useSite()
  const tz = site?.timezone ?? 'UTC'
  const { can } = useTempoContext()
  const load = useCallback(() => { getDataStatus().then(setS).catch((e) => setErr(e.message)) }, [])
  useEffect(load, [load])
  if (err) return <Banner tone="bad" title="Could not load">{err}</Banner>
  if (!s) return <Skeleton h={240} />
  return (
    <div className="tp-stack">
      <section className="tp-card" aria-label="Data freshness"><header><h2>Last successful load</h2></header>
        <table className="tp-table"><thead><tr><th>Data</th><th>Last loaded ({tz})</th><th>Rows</th><th>Waiting to be confirmed</th><th>Rejected rows</th></tr></thead><tbody>
          {s.classes.map((c) => <tr key={`${c.data_class}${c.entity}`}><td>{c.title}</td><td>{c.last_success_at ? fmtTime(c.last_success_at, tz, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : <span className="tp-muted">Never</span>}</td>
            <td>{c.last_rows ?? '—'}</td><td>{c.waiting_batches || '—'}</td><td>{c.rejected_rows ? <Status tone="risk">{c.rejected_rows}</Status> : '—'}</td></tr>)}</tbody></table>
      </section>
      <section className="tp-card" aria-label="Forecast source"><header><h2>Which forecast drives planning</h2></header>
        <div className="tp-body tp-stack">
          <p className="tp-muted" style={{ margin: 0, fontSize: 12.5 }}>Tempo’s own forecast, or the forecast you supplied. If you pick yours and it does not cover an activity completely, Tempo uses its own for that activity and says so. A change applies from the next forecast run.</p>
          {s.sites.map((x) => (
            <label key={x.site_id} className="tp-field" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>{x.name}
              <select value={x.forecast_source} disabled={!can('labour.data.import')} onChange={(e) => void setForecastSource(x.site_id, e.target.value as 'generated' | 'supplied').then(load)}>
                <option value="generated">Tempo’s forecast</option><option value="supplied">Forecast I supplied</option></select></label>))}
          {s.forecast_versions.length > 0 && <table className="tp-table"><thead><tr><th>Supplied forecast</th><th>Periods</th><th>From</th><th>To</th></tr></thead><tbody>
            {s.forecast_versions.map((v) => <tr key={v.site_id + v.version}><td>{v.version}</td><td>{v.rows}</td><td>{fmtTime(v.first, tz, { day: '2-digit', month: 'short' })}</td><td>{fmtTime(v.last, tz, { day: '2-digit', month: 'short' })}</td></tr>)}</tbody></table>}
        </div>
      </section>
      <section className="tp-card" aria-label="Workload source"><header><h2>How workload is counted</h2></header>
        <div className="tp-body">
          <p className="tp-muted" style={{ marginTop: 0, fontSize: 12.5 }}>For each site and activity, workload is counted from one kind only — individual events or period totals — so the same work is never counted twice. The first kind to arrive becomes the one that counts.</p>
          {s.authority.length === 0 ? <p className="tp-muted">Nothing has been loaded yet.</p> : <table className="tp-table"><thead><tr><th>Site</th><th>Activity</th><th>Counted from</th></tr></thead><tbody>
            {s.authority.map((a) => <tr key={a.site_id + a.activity}><td>{a.site_id}</td><td>{a.activity}</td><td>{a.authority === 'bulk' ? 'Period totals' : 'Individual events'}</td></tr>)}</tbody></table>}
        </div>
      </section>
    </div>
  )
}

function ApiTab() {
  const { can } = useTempoContext()
  const { sites } = useSite()
  const [list, setList] = useState<Credential[] | null>(null)
  const [name, setName] = useState('')
  const [siteIds, setSiteIds] = useState<string[]>([])
  const [shown, setShown] = useState<Credential | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const load = useCallback(() => { if (can('labour.configure')) listCredentials().then(setList).catch((e) => setErr(e.message)); else setList([]) }, [can])
  useEffect(load, [load])
  const act = async (fn: () => Promise<Credential>) => { setErr(null); try { const c = await fn(); if (c.secret) setShown(c); load() } catch (e) { setErr((e as Error).message) } }
  const origin = typeof window !== 'undefined' ? window.location.origin : ''
  return (
    <div className="tp-stack">
      <section className="tp-card" aria-label="API credentials"><header><h2>API credentials</h2></header>
        <div className="tp-body tp-stack">
          <p style={{ margin: 0 }}>Let your systems send data directly. A credential can only load data — it cannot sign in or read anything else — and you choose which sites it covers.</p>
          {err && <Banner tone="bad" title="Problem">{err}</Banner>}
          {shown?.secret && <Banner tone="warn" title={`Copy this now — ${shown.name}`}><code style={{ wordBreak: 'break-all', fontSize: 14 }} aria-label="New API secret">{shown.secret}</code><br />{shown.note}</Banner>}
          {can('labour.configure') ? (
            <form className="tp-row" onSubmit={(e) => { e.preventDefault(); void act(() => createCredential(name, siteIds.length ? siteIds : null, 90)).then(() => setName('')) }} aria-label="New credential">
              <label className="tp-field">Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. WMS nightly feed" required minLength={2} /></label>
              <label className="tp-field">Sites<select multiple value={siteIds} onChange={(e) => setSiteIds([...e.target.selectedOptions].map((o) => o.value))}>{sites.map((s) => <option key={s.site_id} value={s.site_id}>{s.name}</option>)}</select></label>
              <button className="tp-btn primary" type="submit">Create credential</button></form>) : <p className="tp-muted">Only an administrator can create credentials.</p>}
          {list && list.length > 0 && <table className="tp-table" aria-label="Credentials"><thead><tr><th>Name</th><th>Starts with</th><th>Sites</th><th>Expires</th><th>Last used</th><th>State</th><th /></tr></thead><tbody>
            {list.map((c) => <tr key={c.id}><td>{c.name}</td><td><code>{c.prefix}…</code></td><td>{c.site_ids?.join(', ') ?? 'All your sites'}</td><td>{c.expires_at ? new Date(c.expires_at).toLocaleDateString() : '—'}</td><td>{c.last_used_at ? new Date(c.last_used_at).toLocaleString() : 'Never'}</td>
              <td><Status tone={c.status === 'active' ? 'ok' : 'neutral'}>{c.status}</Status></td>
              <td>{c.status === 'active' && <span className="tp-row"><button className="tp-btn" onClick={() => void act(() => rotateCredential(c.id))}>Rotate</button><button className="tp-btn danger" onClick={() => void act(() => revokeCredential(c.id))}>Revoke</button></span>}</td></tr>)}</tbody></table>}
        </div>
      </section>
      <section className="tp-card" aria-label="API reference"><header><h2>Sending data</h2></header>
        <div className="tp-body tp-stack">
          <p style={{ margin: 0 }}>Send rows as JSON. Add an <code>Idempotency-Key</code> so a retry returns the same receipt instead of loading twice. The templates below list every field.</p>
          <pre style={{ overflow: 'auto', background: 'var(--tp-surface-2)', padding: 10, borderRadius: 6, fontSize: 12.5 }}>{`curl -X POST ${origin}/v1/imports/batches \\
  -H "Authorization: Bearer tsc_…" -H "Idempotency-Key: feed-2026-10-05" -H "Content-Type: application/json" \\
  -d '{"data_class":"bulk","apply":true,"rows":[{"site":"mel_dc_01","activity":"picking","period_start":"2026-10-05","grain":"day","units":26140}]}'`}</pre>
          <div className="tp-row" role="group" aria-label="Templates">
            {([['master', 'workers', 'Staff'], ['master', 'work_standards', 'Work standards'], ['forecast', null, 'Forecast'], ['bulk', null, 'Workload totals'], ['transactions', null, 'Workload events']] as const).map(([dc, ent, label]) => (
              <button key={label} className="tp-btn" onClick={() => void downloadTemplate(dc, ent)}>⭳ {label} template</button>))}
          </div>
        </div>
      </section>
    </div>
  )
}
