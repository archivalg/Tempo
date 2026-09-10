import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTempoContext } from '../context/TempoContextProvider'

const KNOWN_ROLES = [
  'operations_manager',
  'planner',
  'supervisor',
  'analyst',
  'executive',
  'tenant_admin',
  'finance',
  '3pl_commercial',
  'hr_authorised',
  'integration_restricted',
  'labour_provider',
]

function csv(value: string): string[] {
  return value
    .split(',')
    .map((v) => v.trim())
    .filter(Boolean)
}

export function ContextSetupPage() {
  const { context, setContext } = useTempoContext()
  const navigate = useNavigate()

  const [tenantId, setTenantId] = useState(context?.tenant_id ?? 'ten_demo')
  const [siteIds, setSiteIds] = useState(context?.site_ids.join(', ') ?? 'site_mel_01')
  const [customerIds, setCustomerIds] = useState(context?.customer_ids.join(', ') ?? '')
  const [providerId, setProviderId] = useState(context?.provider_id ?? '')
  const [userId, setUserId] = useState(context?.user_id ?? 'usr_demo')
  const [roles, setRoles] = useState<string[]>(context?.roles ?? ['operations_manager'])

  function toggleRole(role: string) {
    setRoles((current) => (current.includes(role) ? current.filter((r) => r !== role) : [...current, role]))
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setContext({
      tenant_id: tenantId,
      site_ids: csv(siteIds),
      customer_ids: csv(customerIds),
      provider_id: providerId || undefined,
      user_id: userId,
      roles,
      purpose: 'labour.console',
      correlation_id: `cor_${crypto.randomUUID().slice(0, 12)}`,
    })
    navigate('/')
  }

  return (
    <div className="page context-setup">
      <h1>Tempo Console</h1>
      <p className="hint">
        This service has no identity provider yet — see <code>app/dependencies.py</code>'s own docstring in
        services/tempo-api: the <code>X-Tempo-Context</code> header is a disclosed Phase&nbsp;0 stand-in for a real
        token, not a security control. This form builds that header directly; it is not a login.
      </p>
      <form onSubmit={handleSubmit}>
        <label>
          Tenant ID
          <input value={tenantId} onChange={(e) => setTenantId(e.target.value)} required />
        </label>
        <label>
          Site IDs (comma-separated)
          <input value={siteIds} onChange={(e) => setSiteIds(e.target.value)} />
        </label>
        <label>
          Customer IDs (comma-separated, optional)
          <input value={customerIds} onChange={(e) => setCustomerIds(e.target.value)} />
        </label>
        <label>
          Provider ID (only meaningful with the labour_provider role below)
          <input value={providerId} onChange={(e) => setProviderId(e.target.value)} />
        </label>
        <label>
          User ID
          <input value={userId} onChange={(e) => setUserId(e.target.value)} required />
        </label>
        <fieldset>
          <legend>Roles (§5.2 role table — determines which permissions you carry)</legend>
          {KNOWN_ROLES.map((role) => (
            <label key={role} className="checkbox">
              <input type="checkbox" checked={roles.includes(role)} onChange={() => toggleRole(role)} />
              {role}
            </label>
          ))}
        </fieldset>
        <button type="submit">Enter console</button>
      </form>
    </div>
  )
}
