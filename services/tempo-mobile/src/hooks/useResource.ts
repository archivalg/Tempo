import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

export interface Resource<T> { data: T | null; error: string | null; offline: boolean; loading: boolean; refreshing: boolean; reload: () => void; refresh: () => void; updatedAt: Date | null }

/** Loads something from Tempo and keeps the LAST GOOD copy when a refresh fails, so a lost connection never blanks the screen: you see what you had, plus a clear message. */
export function useResource<T>(load: () => Promise<T>, deps: unknown[] = []): Resource<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const live = useRef(true)
  const fn = useRef(load)
  fn.current = load

  const run = useCallback(async (pull: boolean) => {
    if (pull) setRefreshing(true); else setLoading(true)
    try {
      const d = await fn.current()
      if (!live.current) return
      setData(d); setError(null); setOffline(false); setUpdatedAt(new Date())
    } catch (e) {
      if (!live.current) return
      const a = e as ApiError
      setError(a.message || 'Something went wrong.')
      setOffline(a.kind === 'network' || a.kind === 'timeout')
    } finally {
      if (live.current) { setLoading(false); setRefreshing(false) }
    }
  }, [])

  useEffect(() => { live.current = true; void run(false); return () => { live.current = false } }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, offline, loading, refreshing, reload: () => void run(false), refresh: () => void run(true), updatedAt }
}
