/** Times are always shown in the SITE's time zone (where the work happens), not the phone's. */
export function fmt(iso: string, tz: string, opts: Intl.DateTimeFormatOptions): string {
  try { return new Intl.DateTimeFormat('en-AU', { timeZone: tz, ...opts }).format(new Date(iso)) } catch { return iso }
}
export const day = (iso: string, tz: string) => fmt(iso, tz, { weekday: 'short', day: 'numeric', month: 'short' })
export const clock = (iso: string, tz: string) => fmt(iso, tz, { hour: '2-digit', minute: '2-digit', hour12: false })
export const dayClock = (iso: string, tz: string) => `${day(iso, tz)} ${clock(iso, tz)}`
export function hours(minutes: number): string {
  const h = Math.floor(minutes / 60), m = Math.round(minutes % 60)
  return m ? `${h} h ${m} min` : `${h} h`
}
/** "Mon 5 Oct, 06:00 – 14:00" or, for a shift that crosses midnight, "Sat 3 Oct 22:00 – Sun 4 Oct 06:00". */
export function shiftRange(startIso: string, endIso: string, tz: string, overnight: boolean): string {
  return overnight ? `${dayClock(startIso, tz)} – ${dayClock(endIso, tz)}` : `${day(startIso, tz)}, ${clock(startIso, tz)} – ${clock(endIso, tz)}`
}
/** Today's date in the site's zone as YYYY-MM-DD (used to group "Today" / "Tomorrow"). */
export const localDate = (d: Date, tz: string): string => new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(d)
