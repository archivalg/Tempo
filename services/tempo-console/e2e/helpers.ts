import type { Page } from '@playwright/test'

// Matches services/tempo-api/scripts/seed_e2e.py — see that script's
// docstring for why this suite reseeds a fixed, known dataset before
// every run rather than relying on whatever's in a dev database.
export const TENANT_ID = 'ten_e2e'
export const SITE_ID = 'site_e2e_01'
export const KIOSK_WORKER_ID = 'wrk_0'
export const KIOSK_PIN = '1234'

const STORAGE_KEY = 'tempo-console.context'

export interface ContextOptions {
  userId?: string
  roles?: string[]
  siteIds?: string[]
  customerIds?: string[]
  providerId?: string
}

/** Sets the console's X-Tempo-Context directly via localStorage — the
 * same mechanism the real Context Setup page uses (see
 * src/context/TempoContextProvider.tsx), just skipping the form for
 * every test except the one that verifies the form itself. localStorage
 * is origin-scoped, so the page must already have navigated once before
 * this can be called.
 */
export async function setContext(page: Page, options: ContextOptions = {}): Promise<void> {
  await page.goto('/setup')
  const context = {
    tenant_id: TENANT_ID,
    site_ids: options.siteIds ?? [SITE_ID],
    customer_ids: options.customerIds ?? [],
    provider_id: options.providerId,
    user_id: options.userId ?? 'usr_e2e',
    roles: options.roles ?? ['operations_manager'],
    purpose: 'labour.console',
    correlation_id: `cor_e2e_${Date.now()}`,
  }
  await page.evaluate(
    ([key, value]) => localStorage.setItem(key as string, value as string),
    [STORAGE_KEY, JSON.stringify(context)],
  )
}
