import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'
import { getAccess, logout, type Access } from '../api/session'
import type { TempoContext } from '../api/types'

// The session is the server's: an HttpOnly cookie proves who you are and /me/access says what you may do.
// Nothing here is authoritative — it only decides what to *show*. The API re-checks every request.
type Status = 'loading' | 'anonymous' | 'authenticated' | 'error'

interface SessionValue {
  status: Status
  access: Access | null
  /** Legacy shape the pre-Gate-1 pages consume, derived from the server's answer. */
  context: TempoContext | null
  can: (permission: string) => boolean
  reload: () => Promise<void>
  signOut: () => Promise<void>
  error: string | null
}

const Ctx = createContext<SessionValue | undefined>(undefined)

export function TempoContextProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>('loading')
  const [access, setAccess] = useState<Access | null>(null)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async () => {
    try {
      const a = await getAccess()
      setAccess(a)
      setStatus('authenticated')
      setError(null)
    } catch (e) {
      setAccess(null)
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setStatus('anonymous')
      } else {
        setStatus('error')
        setError(e instanceof Error ? e.message : 'unable to reach the Tempo API')
      }
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  const signOut = useCallback(async () => {
    try {
      await logout()
    } catch {
      /* session may already be gone */
    }
    setAccess(null)
    setStatus('anonymous')
  }, [])

  const value = useMemo<SessionValue>(() => {
    const context: TempoContext | null =
      access && access.tenant_id
        ? { tenant_id: access.tenant_id, site_ids: access.site_ids, customer_ids: access.customer_ids, user_id: access.user_id, roles: access.roles, purpose: 'labour.console', correlation_id: '', provider_id: access.provider_ids[0] }
        : null
    return { status, access, context, can: (p) => !!access?.permissions.includes(p), reload, signOut, error }
  }, [status, access, reload, signOut, error])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTempoContext(): SessionValue {
  const value = useContext(Ctx)
  if (!value) throw new Error('useTempoContext must be used within a TempoContextProvider')
  return value
}
