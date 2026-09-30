/** Wall-clock <-> UTC conversion for an IANA timezone, DST-safe (no library). */
function offsetMs(d: Date, tz: string): number {
  const p = new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }).formatToParts(d)
  const g = (t: string) => Number(p.find((x) => x.type === t)!.value)
  return Date.UTC(g('year'), g('month') - 1, g('day'), g('hour'), g('minute'), g('second')) - d.getTime()
}
/** "2026-09-30T06:00" typed in `tz` → UTC ISO string. */
export function zonedToUtcIso(local: string, tz: string): string {
  const guess = new Date(`${local}:00Z`)
  let t = guess.getTime() - offsetMs(guess, tz)
  t = guess.getTime() - offsetMs(new Date(t), tz) // second pass settles DST edges
  return new Date(t).toISOString()
}
/** UTC ISO → "YYYY-MM-DDTHH:mm" wall-clock in `tz` (for <input type="datetime-local">). */
export function utcToZonedInput(iso: string, tz: string): string {
  const p = new Intl.DateTimeFormat('en-CA', { timeZone: tz, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).formatToParts(new Date(iso))
  const g = (t: string) => p.find((x) => x.type === t)!.value
  return `${g('year')}-${g('month')}-${g('day')}T${g('hour')}:${g('minute')}`
}
export const localMidnightUtc = (date: string, tz: string) => zonedToUtcIso(`${date}T00:00`, tz)
