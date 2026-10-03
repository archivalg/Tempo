/** Turns the deep link carried in a notification (tempo://shifts/123, tempo://offers/9, …) into an in-app route. Unknown links go to the home list: never a crash, never a blank screen. */
export function routeForDeepLink(link: string | null | undefined): string {
  if (!link) return '/shifts'
  const m = link.match(/^[a-z-]+:\/\/([a-z-]+)(?:\/([A-Za-z0-9_-]+))?/i)
  if (!m) return '/shifts'
  const [, area, id] = m
  switch (area) {
    case 'shifts': return id ? `/shifts/${id}` : '/shifts'
    case 'offers': return id ? `/offers?focus=${id}` : '/offers'
    case 'changes': return '/changes'
    case 'leave': return '/requests'
    case 'notifications': return '/notifications'
    default: return '/shifts'
  }
}
