import { routeForDeepLink } from '../src/push/links'
import { clock, hours, localDate, shiftRange } from '../src/lib/time'
import { zonedInstant } from '../app/(app)/requests'

describe('deep links', () => {
  it.each([
    ['tempo://shifts/abc-123', '/shifts/abc-123'], ['tempo://shifts', '/shifts'], ['tempo://offers/o9', '/offers?focus=o9'], ['tempo://changes', '/changes'],
    ['tempo-test://leave/l1', '/requests'], ['tempo://notifications', '/notifications'], ['tempo://nonsense/1', '/shifts'], ['garbage', '/shifts'], [null, '/shifts'], [undefined, '/shifts'],
  ])('%s -> %s', (link, route) => { expect(routeForDeepLink(link as string | null | undefined)).toBe(route) })
})

describe('site-zone times', () => {
  it('shows times in the site zone, not the phone zone', () => {
    expect(clock('2026-10-05T20:00:00Z', 'Australia/Melbourne')).toBe('07:00')
    expect(clock('2026-10-05T20:00:00Z', 'Australia/Perth')).toBe('04:00')
  })
  it('labels an overnight shift across midnight and keeps real elapsed time on a daylight-saving night', () => {
    const start = '2026-10-03T12:00:00Z', end = '2026-10-03T19:00:00Z' // 22:00 AEST to 06:00 AEDT after the clocks go forward = 7 real hours
    expect(shiftRange(start, end, 'Australia/Melbourne', true)).toMatch(/Sat,? 3 Oct.*22:00.*Sun,? 4 Oct.*06:00/)
    expect(hours(7 * 60)).toBe('7 h')
    expect(hours(7 * 60 + 30)).toBe('7 h 30 min')
  })
  it('works out the site-local date', () => { expect(localDate(new Date('2026-10-03T15:30:00Z'), 'Australia/Melbourne')).toBe('2026-10-04') })
  it('converts a picked wall-clock time to the exact site instant, including across the daylight-saving change', () => {
    expect(zonedInstant(new Date(2026, 6, 10, 9, 0), 'Australia/Melbourne')).toBe('2026-07-09T23:00:00.000Z')   // winter, UTC+10
    expect(zonedInstant(new Date(2026, 9, 5, 9, 0), 'Australia/Melbourne')).toBe('2026-10-04T22:00:00.000Z')    // after the change, UTC+11
    expect(zonedInstant(new Date(2026, 9, 3, 22, 0), 'Australia/Melbourne')).toBe('2026-10-03T12:00:00.000Z')   // the night before it
  })
})
