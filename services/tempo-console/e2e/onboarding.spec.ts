import { expect, test } from '@playwright/test'
import { setContext, SITE_ID } from './helpers'

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

test('tenant admin enrols a clock-in PIN that then works at the Kiosk', async ({ page }) => {
  await setContext(page, { roles: ['tenant_admin'] })
  await page.goto('/onboarding')

  const workerId = 'wrk_2' // seeded by seed_named_roster_scenario, no credential yet
  const pin = '5150'
  const credentialsSection = page.locator('section:has(h2:has-text("Clock-in credentials"))')
  await credentialsSection.getByLabel('Worker ID').fill(workerId)
  await credentialsSection.getByLabel('PIN').fill(pin)
  await credentialsSection.locator('button:has-text("Enrol credential")').click()
  await expect(credentialsSection).toContainText(`Worker ${workerId}: has a PIN, no NFC tag.`)

  // Prove the enrolment is real, not just a UI success message: the PIN
  // must actually authenticate at the Kiosk (operations_manager context,
  // same as every other console page — enrolment itself needed tenant_admin).
  await setContext(page, { roles: ['operations_manager'] })
  await page.goto('/kiosk')
  await page.getByLabel('Site ID').fill(SITE_ID)
  await page.getByLabel('PIN').fill(pin)
  await page.click('button:has-text("Identify")')
  await expect(page.locator('h2')).toContainText(workerId)
})
