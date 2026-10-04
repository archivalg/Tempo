import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { addCertification, createProvider, listProviders, listSuppliedWorkers, registerSuppliedWorker } from '../api/providers'
import type { SuppliedWorker } from '../api/types'
import { useSite } from '../components/AppShell'
import { HelpLink } from '../components/HelpLink'
import { Banner, Drawer, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useTempoContext } from '../context/TempoContextProvider'
import { useApi } from '../hooks/useApi'
import { fmtTime } from '../lib/format'

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))
const today = () => new Date().toISOString().slice(0, 10)

/** Labour-hire providers, the workers they supply to your sites, and the skills each worker is certified for. */
export function LabourProvidersPage() {
  const { context, can } = useTempoContext()
  const { sites } = useSite()
  const canManage = can('labour.configure') || can('labour.provider.manage')
  const providers = useApi(() => (context ? listProviders(context) : Promise.resolve([])), [context])
  const [providerId, setProviderId] = useState(context?.provider_id ?? '')
  useEffect(() => { if (!providerId && providers.data?.length) setProviderId(providers.data[0].provider_id) }, [providers.data, providerId])
  const workers = useApi(() => (context && providerId ? listSuppliedWorkers(context, providerId) : Promise.resolve([] as SuppliedWorker[])), [context, providerId])
  const siteName = (id: string) => sites.find((s) => s.site_id === id)?.name ?? id
  const provider = providers.data?.find((p) => p.provider_id === providerId)
  const knownSkills = useMemo(() => [...new Set((workers.data ?? []).flatMap((w) => w.certifications.map((c) => c.skill_code)))].sort(), [workers.data])

  const [drawer, setDrawer] = useState<null | { kind: 'provider' } | { kind: 'worker' } | { kind: 'skill'; worker: SuppliedWorker }>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [site, setSite] = useState('')
  const [ref, setRef] = useState('')
  const [skill, setSkill] = useState('')
  const [from, setFrom] = useState(today())
  const [to, setTo] = useState('')
  const open = (d: NonNullable<typeof drawer>) => { setErr(null); setDrawer(d); setSkill(''); setFrom(today()); setTo(''); setSite(sites[0]?.site_id ?? ''); setRef(''); setName('') }
  async function run(fn: () => Promise<unknown>, after: () => void) {
    setBusy(true); setErr(null)
    try { await fn(); setDrawer(null); after() } catch (e) { setErr(msg(e)) } finally { setBusy(false) }
  }
  if (!context) return <Empty title="Not signed in" />

  return (
    <>
      <PageHead title="Team & skills" sub="Labour-hire providers, the workers they supply, and what each worker is certified to do.">
        <HelpLink id="roles" />
        {can('labour.configure') && <button className="tp-btn" onClick={() => open({ kind: 'provider' })}>Add a provider</button>}
      </PageHead>
      <Banner tone="info" title="Providers supply people, Tempo does the rostering">A provider can keep its own workers and certifications up to date. It cannot create or edit roster shifts; those stay with your planners.</Banner>
      {providers.error ? <Banner tone="bad" title="Could not load providers">{msg(providers.error)} <button className="tp-btn" onClick={providers.reload}>Try again</button></Banner> : null}

      <section className="tp-card" aria-label="Supplied workers">
        <header>
          <h2>{provider ? provider.name : 'Supplied workers'}</h2>
          <div className="tp-row">
            {provider && <Status tone={provider.status === 'active' ? 'ok' : 'neutral'}>{provider.status === 'active' ? 'Active' : provider.status}</Status>}
            {canManage && providerId && <button className="tp-btn primary" onClick={() => open({ kind: 'worker' })}>Add a worker</button>}
          </div>
        </header>
        <div className="tp-body tp-stack">
          {!providers.data ? <Skeleton h={40} /> : providers.data.length === 0 ? (
            <Empty title="No providers yet">{can('labour.configure') ? 'Add the labour-hire companies that supply workers to your sites, then add their workers here.' : 'Ask an administrator to add your labour-hire providers.'}</Empty>
          ) : (
            <label className="tp-field" style={{ maxWidth: 360 }}>Provider
              <select value={providerId} onChange={(e) => setProviderId(e.target.value)}>{providers.data.map((p) => <option key={p.provider_id} value={p.provider_id}>{p.name}</option>)}</select></label>
          )}
          {providerId && workers.error ? <Banner tone="bad" title="Could not load this provider's workers">{msg(workers.error)} <button className="tp-btn" onClick={workers.reload}>Try again</button></Banner> : null}
          {providerId && !workers.data && !workers.error ? <Skeleton h={140} /> : null}
          {providerId && workers.data && workers.data.length === 0 ? <Empty title="No workers from this provider yet">{canManage ? 'Add a worker, then record the skills they are certified for.' : 'Workers appear here once they are added.'}</Empty> : null}
          {workers.data && workers.data.length > 0 && (
            <div style={{ overflow: 'auto' }}>
              <table className="tp-table">
                <thead><tr><th>Worker</th><th>Home site</th><th>Skills</th><th>Upcoming shifts</th>{canManage && <th />}</tr></thead>
                <tbody>{workers.data.map((w) => (
                  <tr key={w.worker_id}>
                    <td><code>{w.worker_id}</code><div className="tp-muted" style={{ fontSize: 12 }}>{w.status === 'active' ? 'Active' : w.status}</div></td>
                    <td>{siteName(w.home_site)}</td>
                    <td>{w.certifications.length === 0 ? <span className="tp-muted">none recorded</span> : <span className="tp-row" style={{ flexWrap: 'wrap' }}>{w.certifications.map((c) => (
                      <Status key={c.id} tone={c.valid_to && new Date(c.valid_to) < new Date() ? 'bad' : 'ok'} title={`From ${fmtTime(c.valid_from, 'UTC', { day: '2-digit', month: 'short', year: 'numeric' })}${c.valid_to ? ` to ${fmtTime(c.valid_to, 'UTC', { day: '2-digit', month: 'short', year: 'numeric' })}` : ''}`}>{c.skill_code}{c.valid_to && new Date(c.valid_to) < new Date() ? ' (expired)' : ''}</Status>))}</span>}</td>
                    <td className="tp-num">{w.upcoming_shifts.length === 0 ? <span className="tp-muted">none</span> : w.upcoming_shifts.length}</td>
                    {canManage && <td><button className="tp-btn" onClick={() => open({ kind: 'skill', worker: w })}>Add a skill</button></td>}
                  </tr>))}</tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      {drawer?.kind === 'provider' && (
        <Drawer title="Add a provider" onClose={() => setDrawer(null)}>
          <form className="tp-stack" onSubmit={(e: FormEvent) => { e.preventDefault(); void run(() => createProvider(context, name.trim()), () => { providers.reload() }) }}>
            {err && <Banner tone="bad" title="Could not add the provider">{err}</Banner>}
            <label className="tp-field">Company name<input value={name} onChange={(e) => setName(e.target.value)} required autoFocus /></label>
            <button className="tp-btn primary" disabled={busy || !name.trim()}>Add provider</button>
          </form>
        </Drawer>
      )}
      {drawer?.kind === 'worker' && (
        <Drawer title={`Add a worker from ${provider?.name ?? 'this provider'}`} onClose={() => setDrawer(null)}>
          <form className="tp-stack" onSubmit={(e: FormEvent) => { e.preventDefault(); void run(() => registerSuppliedWorker(context, providerId, { home_site: site, ...(ref.trim() ? { source_ref: ref.trim() } : {}) }), () => { workers.reload() }) }}>
            {err && <Banner tone="bad" title="Could not add the worker">{err}</Banner>}
            <label className="tp-field">Home site<select value={site} onChange={(e) => setSite(e.target.value)} required>{sites.map((s) => <option key={s.site_id} value={s.site_id}>{s.name}</option>)}</select></label>
            <label className="tp-field">Provider's own reference (optional)<input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Their staff number" /></label>
            <button className="tp-btn primary" disabled={busy || !site}>Add worker</button>
            <p className="tp-muted" style={{ fontSize: 12 }}>The worker gets a Tempo ID automatically. Add their skills next so they can be rostered to skilled roles.</p>
          </form>
        </Drawer>
      )}
      {drawer?.kind === 'skill' && (
        <Drawer title="Add a skill" onClose={() => setDrawer(null)}>
          <form className="tp-stack" onSubmit={(e: FormEvent) => { e.preventDefault(); void run(() => addCertification(context, providerId, drawer.worker.worker_id, { skill_code: skill.trim().toLowerCase(), valid_from: new Date(`${from}T00:00:00`).toISOString(), ...(to ? { valid_to: new Date(`${to}T23:59:59`).toISOString() } : {}) }), () => { workers.reload() }) }}>
            {err && <Banner tone="bad" title="Could not add the skill">{err}</Banner>}
            <p className="tp-muted" style={{ margin: 0 }}>For worker <code>{drawer.worker.worker_id}</code> at {siteName(drawer.worker.home_site)}.</p>
            <label className="tp-field">Skill<input value={skill} onChange={(e) => setSkill(e.target.value)} list="known-skills" required autoFocus placeholder="forklift, picker, packer…" /></label>
            <datalist id="known-skills">{knownSkills.map((k) => <option key={k} value={k} />)}</datalist>
            <div className="tp-cols2">
              <label className="tp-field">Valid from<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} required /></label>
              <label className="tp-field">Valid until (optional)<input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} /></label>
            </div>
            <button className="tp-btn primary" disabled={busy || !skill.trim() || !from}>Add skill</button>
            <p className="tp-muted" style={{ fontSize: 12 }}>A skill with an end date shows as expired afterwards and raises an exception before it lapses.</p>
          </form>
        </Drawer>
      )}
    </>
  )
}
