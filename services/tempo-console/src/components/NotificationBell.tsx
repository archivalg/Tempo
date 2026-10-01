import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getNotifications, markAllNoticesRead, markNoticeRead, type Notice } from '../api/ops'
import { fmtAge } from '../lib/format'

const ICON = { urgent: '✕', action: '▲', info: '●' } as const

/** Unread count + the latest notices. Polls politely (and when the tab regains focus); never blocks the page if the API is slow. */
export function NotificationBell() {
  const [data, setData] = useState<{ unread: number; items: Notice[] } | null>(null)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const nav = useNavigate()
  const load = useCallback(() => { getNotifications().then(setData).catch(() => undefined) }, [])
  useEffect(() => {
    load()
    const t = setInterval(load, 30_000)
    const onVis = () => { if (document.visibilityState === 'visible') load() }
    document.addEventListener('visibilitychange', onVis)
    return () => { clearInterval(t); document.removeEventListener('visibilitychange', onVis) }
  }, [load])
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    const onClick = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('keydown', onKey); document.addEventListener('mousedown', onClick)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('mousedown', onClick) }
  }, [open])
  const unread = data?.unread ?? 0
  const go = (n: Notice) => { void markNoticeRead(n.id).then(load); setOpen(false); if (n.link) nav(n.link) }
  return (
    <div className="tp-bell" ref={box}>
      <button className="tp-iconbtn" aria-haspopup="true" aria-expanded={open} aria-label={`Notifications, ${unread} unread`} onClick={() => { setOpen(!open); load() }}>
        <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ verticalAlign: "-3px" }}><path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" /><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" /></svg>{unread > 0 && <span className="tp-count" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
      </button>
      {open && (
        <div className="tp-bellpanel" role="region" aria-label="Notifications">
          <div className="tp-row" style={{ justifyContent: 'space-between' }}><strong>Notifications</strong>
            <button className="tp-btn" disabled={unread === 0} onClick={() => void markAllNoticesRead().then(load)}>Mark all read</button></div>
          {!data || data.items.length === 0 ? <p className="tp-muted">Nothing needs your attention.</p> : (
            <ul className="tp-list" style={{ maxHeight: 360, overflow: 'auto' }}>
              {data.items.map((n) => (
                <li key={n.id}><button className={`tp-notice${n.read_at ? '' : ' unread'}`} onClick={() => go(n)}>
                  <span className={`tp-badge ${n.severity === 'urgent' ? 'bad' : n.severity === 'action' ? 'risk' : 'neutral'}`}><span aria-hidden="true">{ICON[n.severity]}</span>{n.severity === 'urgent' ? 'Urgent' : n.severity === 'action' ? 'Action' : 'Info'}</span>
                  <span className="t">{n.title}</span>{n.body && <span className="s">{n.body}</span>}
                  <span className="s">{fmtAge((Date.now() - new Date(n.created_at).getTime()) / 1000)} ago{n.read_at ? '' : ' · unread'}</span></button></li>))}
            </ul>)}
        </div>
      )}
    </div>
  )
}
