import { expect, test } from '@playwright/test'
import { setContext } from './helpers'

test('tenant admin registers a tenant scope and a connection', async ({ page }) => {
  await setContext(page, { roles: ['tenant_admin'] })
  await page.goto('/onboarding')
  await expect(page.locator('h1')).toHaveText('Onboarding')

  await expect(page.locator('h2:has-text("Connector catalogue")')).toBeVisible()
  await expect(page.locator('table').first()).toContainText('deputy')

  const siteId = `site_e2e_onboard_${Date.now()}`
  await page.locator('section:has(h2:has-text("Tenant scopes")) input').first().fill(siteId)
  await page.click('button:has-text("Register scope")')
  await expect(page.locator('section:has(h2:has-text("Tenant scopes")) li')).toContainText(siteId)

  const connectionsSection = page.locator('section:has(h2:has-text("Connections"))')
  await connectionsSection.locator('input').first().fill(siteId)
  await connectionsSection.locator('button:has-text("Register connection")').click()

  const connectionsTable = connectionsSection.locator('table')
  await expect(connectionsTable).toContainText(siteId)
  // Registering never wires up a live vendor credential — see the page's
  // own disclosed hint — so the new connection must stay pending_credentials.
  await expect(connectionsTable).toContainText('pending_credentials')
})
