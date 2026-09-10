import { expect, test } from '@playwright/test'
import { SITE_ID, TENANT_ID } from './helpers'

// The one spec that exercises the real Context Setup form end to end,
// rather than the localStorage shortcut every other spec uses (see
// helpers.ts) — this is the test that actually proves the form works.
test('context setup form builds a working X-Tempo-Context and lands on the console', async ({ page }) => {
  await page.goto('/setup')
  await expect(page.locator('h1')).toHaveText('Tempo Console')

  await page.getByLabel('Tenant ID').fill(TENANT_ID)
  await page.getByLabel(/Site IDs/).fill(SITE_ID)
  await page.getByLabel('User ID').fill('usr_e2e_form')

  // operations_manager is checked by default; add tenant_admin too so the
  // resulting context can reach onboarding pages later in a real click.
  await page.getByRole('checkbox', { name: 'tenant_admin' }).check()

  await page.click('button:has-text("Enter console")')

  await page.waitForURL('/')
  const stored = await page.evaluate(() => localStorage.getItem('tempo-console.context'))
  expect(stored).toBeTruthy()
  const context = JSON.parse(stored as string)
  expect(context.tenant_id).toBe(TENANT_ID)
  expect(context.site_ids).toEqual([SITE_ID])
  expect(context.roles).toContain('operations_manager')
  expect(context.roles).toContain('tenant_admin')
})
