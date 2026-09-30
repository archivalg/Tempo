export function fmtTime(iso: string | null | undefined, tz: string, opts: Intl.DateTimeFormatOptions = { hour: '2-digit', minute: '2-digit', hour12: false }): string {
  if (!iso) return '—'
  return new Intl.DateTimeFormat('en-AU', { timeZone: tz, ...opts }).format(new Date(iso))
}
export const fmtDay = (iso: string, tz: string) => fmtTime(iso, tz, { weekday: 'short', day: '2-digit', month: 'short' })
export function fmtAge(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)} min`
  if (s < 172800) return `${(s / 3600).toFixed(1)} h`
  return `${Math.round(s / 86400)} d`
}
export const fmtNum = (n: number | null | undefined, digits = 0) => (n == null ? '—' : n.toLocaleString('en-AU', { maximumFractionDigits: digits }))
export const fmtMoney = (n: number | null | undefined) => (n == null ? '—' : n.toLocaleString('en-AU', { style: 'currency', currency: 'AUD', maximumFractionDigits: 0 }))
/** Local wall-clock hour (0-23) of an instant in a timezone. */
export function localHour(iso: string, tz: string): number {
  return Number(new Intl.DateTimeFormat('en-GB', { timeZone: tz, hour: '2-digit', hour12: false }).format(new Date(iso))) % 24
}
export function localDate(d: Date, tz: string): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: tz }).format(d) // YYYY-MM-DD
}
