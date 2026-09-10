import { expect, test } from '@playwright/test'
import { setContext, SITE_ID } from './helpers'

test('tenant admin registers a provider, a labour_provider caller manages its own supplied workers', async ({
  page,
}) => {
  await setContext(page, { roles: ['tenant_admin'] })
  await page.goto('/providers')
  await expect(page.locator('h1')).toHaveText('Labour providers')

  const providerName = `Acme Labour Hire ${Date.now()}`
  const providersSection = page.locator('section:has(h2:has-text("Providers"))')
  await providersSection.getByLabel('Name').fill(providerName)
  await providersSection.locator('button:has-text("Register provider")').click()
  await expect(providersSection.locator('table')).toContainText(providerName)

  const providerId = await providersSection
    .locator('tr', { hasText: providerName })
    .locator('td')
    .first()
    .textContent()
  expect(providerId).toBeTruthy()

  // Switch to the labour_provider role this provider would actually use —
  // it must only ever manage its own provider_id, never another's.
  await setContext(page, { roles: ['labour_provider'], providerId: providerId! })
  await page.goto('/providers')

  const workersSection = page.locator('section:has(h2:has-text("Supplied workers"))')
  await expect(workersSection.getByLabel('Provider ID')).toHaveValue(providerId!)

  await workersSection.getByLabel('Home site').fill(SITE_ID)
  await workersSection.locator('button:has-text("Register worker")').click()
  await expect(workersSection.locator('table')).toContainText(SITE_ID)

  const workerId = await workersSection.locator('table tbody tr td').first().textContent()
  expect(workerId).toBeTruthy()

  await workersSection.getByLabel('Worker ID').fill(workerId!)
  await workersSection.getByLabel('Skill code').fill('forklift_lo')
  await workersSection.getByLabel('Valid from').fill('2026-01-01T00:00')
  await workersSection.locator('button:has-text("Add certification")').click()

  await expect(workersSection.locator('table tbody tr')).toContainText('forklift_lo')
})

test('a labour_provider caller cannot view another provider\'s supplied workers', async ({ page }) => {
  await setContext(page, { roles: ['tenant_admin'] })
  await page.goto('/providers')
  const providersSection = page.locator('section:has(h2:has-text("Providers"))')

  const otherProviderName = `Beta Staffing ${Date.now()}`
  await providersSection.getByLabel('Name').fill(otherProviderName)
  await providersSection.locator('button:has-text("Register provider")').click()
  await expect(providersSection.locator('table')).toContainText(otherProviderName)
  const otherProviderId = await providersSection
    .locator('tr', { hasText: otherProviderName })
    .locator('td')
    .first()
    .textContent()

  await setContext(page, { roles: ['labour_provider'], providerId: 'prov_not_mine' })
  await page.goto('/providers')
  // The Providers section itself also 403s here (labour_provider has no
  // labour.read) — expected and separate from what this test checks, so
  // scope the assertion to the Supplied workers section specifically.
  const workersSection = page.locator('section:has(h2:has-text("Supplied workers"))')
  await workersSection.getByLabel('Provider ID').fill(otherProviderId!)
  await workersSection.locator('button:has-text("Refresh")').click()

  await expect(workersSection.locator('.error-banner')).toBeVisible()
  await expect(workersSection.locator('.error-banner')).toContainText("provider_id does not match")
})
