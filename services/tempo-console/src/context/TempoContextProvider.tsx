import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import type { TempoContext } from '../api/types'

// The backend has no real identity provider yet (app/dependencies.py's own
// docstring: "a Phase 0 stand-in, not a security control, and must not
// reach production" — see services/tempo-api README). This console mirrors
// that honestly rather than hiding it behind a fake "login" screen: the
// context-setup page below is a form for the same fields a real token
// would carry, stored in localStorage, not a credential exchange.
const STORAGE_KEY = 'tempo-console.context'

function loadStored(): TempoContext | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as TempoContext) : null
  } catch {
    return null
  }
}

interface TempoContextValue {
  context: TempoContext | null
  setContext: (context: TempoContext) => void
  clearContext: () => void
}

const Ctx = createContext<TempoContextValue | undefined>(undefined)

export function TempoContextProvider({ children }: { children: ReactNode }) {
  const [context, setContextState] = useState<TempoContext | null>(() => loadStored())

  const setContext = useCallback((next: TempoContext) => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    setContextState(next)
  }, [])

  const clearContext = useCallback(() => {
    localStorage.removeItem(STORAGE_KEY)
    setContextState(null)
  }, [])

  const value = useMemo(() => ({ context, setContext, clearContext }), [context, setContext, clearContext])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useTempoContext(): TempoContextValue {
  const value = useContext(Ctx)
  if (!value) throw new Error('useTempoContext must be used within a TempoContextProvider')
  return value
}
