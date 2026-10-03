import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, setExpiredHandler } from '../api/client'
import * as ep from '../api/endpoints'
import type { Profile } from '../api/types'
import * as store from './storage'
import { unregisterPush } from '../push/register'

type State = 'loading' | 'signedOut' | 'signedIn'
interface Ctx {
  state: State
  profile: Profile | null
  notice: string | null             // why the person is signed out ("Your session has ended…")
  mfaChallenge: string | null
  signIn: (username: string, password: string) => Promise<void>
  submitMfa: (code: string) => Promise<void>
  signOut: () => Promise<void>
  reloadProfile: () => Promise<void>
}
const C = createContext<Ctx | null>(null)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>('loading')
  const [profile, setProfile] = useState<Profile | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [mfaChallenge, setMfa] = useState<string | null>(null)
  const alive = useRef(true)

  const finish = useCallback((why: string | null) => { setProfile(null); setState('signedOut'); setNotice(why) }, [])
  const reloadProfile = useCallback(async () => { setProfile(await ep.getProfile()) }, [])

  useEffect(() => {
    alive.current = true
    setExpiredHandler(() => { if (alive.current) finish('Your session has ended. Please sign in again.') })
    ;(async () => {
      const s = await store.loadSession()
      if (!s) return finish(null)
      try {
        const p = await ep.getProfile()
        if (alive.current) { setProfile(p); setState('signedIn') }
      } catch (e) {
        // A connection problem at start-up must not sign the person out: keep the session and let the screens show the error and retry.
        if (e instanceof ApiError && e.kind === 'network') { if (alive.current) setState('signedIn') } else if (alive.current) finish(null)
      }
    })()
    return () => { alive.current = false }
  }, [finish])

  const accept = useCallback(async (r: { access_token?: string; refresh_token?: string; expires_at?: string; refresh_expires_at?: string }) => {
    await store.saveSession({ access: r.access_token!, refresh: r.refresh_token!, accessExpiresAt: r.expires_at!, refreshExpiresAt: r.refresh_expires_at! })
    try {
      setProfile(await ep.getProfile())
    } catch (e) {
      await store.clearSession()
      if (e instanceof ApiError && e.kind === 'forbidden') throw new ApiError('forbidden', 'This sign-in is for employees. Managers use the Tempo website.', 403)
      throw e
    }
    setMfa(null); setNotice(null); setState('signedIn')
  }, [])

  const value = useMemo<Ctx>(() => ({
    state, profile, notice, mfaChallenge, reloadProfile,
    signIn: async (u, p) => {
      const r = await ep.login(u.trim(), p)
      if (r.status === 'mfa_required') { setMfa(r.challenge ?? null); return }
      await accept(r)
    },
    submitMfa: async (code) => { if (mfaChallenge) await accept(await ep.loginMfa(mfaChallenge, code.trim())) },
    signOut: async () => {
      await unregisterPush().catch(() => undefined)   // this phone stops receiving this person's notifications
      await ep.logout().catch(() => undefined)
      await store.clearSession()
      finish(null)
    },
  }), [state, profile, notice, mfaChallenge, accept, finish, reloadProfile])
  return <C.Provider value={value}>{children}</C.Provider>
}

export function useSession(): Ctx {
  const v = useContext(C)
  if (!v) throw new Error('useSession must be inside SessionProvider')
  return v
}
