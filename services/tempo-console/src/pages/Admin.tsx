import { useState } from 'react'
import { apiRequest } from '../api/client'
import { Banner, Empty, PageHead, Skeleton, Status } from '../components/ui'
import { useApi } from '../hooks/useApi'
import { useSite } from '../components/AppShell'
import { fmtTime } from '../lib/format'

interface Device { device_id: string; name: string | null; site_ids: string[]; status: string; enrolled_at: string | null; last_seen_at: string | null; enrolment_code: string | null }

export default function AdminPage() {
  const { site, sites } = useSite()
  const [nonce, setNonce] = useState(0)
  const [name, setName] = useState('')
  const [code, setCode] = useState<{ device: string; code: string } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const q = useApi(() => apiRequest<Device[]>('/devices'), [nonce])
  async function create() {
    setErr(null)
    try {
      const d = await apiRequest<Device>('/devices', { method: 'POST', body: { name, site_ids: [site!.site_id] } })
      setCode({ device: d.name ?? d.device_id, code: d.enrolment_code! }); setName(''); setNonce((n) => n + 1)
    } catch (e) { setErr(e instanceof Error ? e.message : 'Could not create the device') }
  }
  async function disable(id: string) { await apiRequest(`/devices/${id}/disable`, { method: 'POST' }); setNonce((n) => n + 1) }
  return (
    <>
      <PageHead title="Administration" sub="Kiosk devices for the selected site" />
      {err && <Banner tone="bad" title="Error">{err}</Banner>}
      {code && <Banner tone="warn" title={`Enrolment code for ${code.device} — shown once`}><code style={{ fontSize: 15 }}>{code.code}</code><div>Enter it on the kiosk at /kiosk within 15 minutes. It cannot be shown again.</div></Banner>}
      <section className="tp-card"><header><h2>Kiosk devices</h2></header>
        <div className="tp-body tp-row">
          <label className="tp-field">Device name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Dock 2 kiosk" /></label>
          <button className="tp-btn primary" disabled={!name.trim() || !site} onClick={() => void create()}>Create &amp; get enrolment code</button>
          <span className="tp-muted">Binds to {site?.name}. You can only bind sites inside your own grants ({sites.length}).</span>
        </div>
        {!q.data ? <div className="tp-body"><Skeleton h={80} /></div> : q.data.length === 0 ? <Empty title="No devices yet" /> : (
          <table className="tp-table"><thead><tr><th>Name</th><th>Sites</th><th>Status</th><th>Last seen</th><th /></tr></thead><tbody>
            {q.data.map((d) => (<tr key={d.device_id}><td>{d.name}</td><td>{d.site_ids.join(', ')}</td><td><Status tone={d.status === 'active' ? 'ok' : d.status === 'pending' ? 'risk' : 'bad'}>{d.status}</Status></td><td>{d.last_seen_at ? fmtTime(d.last_seen_at, site?.timezone ?? 'UTC', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'}</td><td>{d.status !== 'disabled' && <button className="tp-btn danger" onClick={() => void disable(d.device_id)}>Disable</button>}</td></tr>))}
          </tbody></table>
        )}
      </section>
      <p className="tp-muted">Users, grants, branding and policies arrive with the tenant-admin module (Gate 1 remainder).</p>
    </>
  )
}
