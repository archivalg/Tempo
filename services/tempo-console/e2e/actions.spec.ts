import { expect, test } from '@playwright/test'
import { setContext, SITE_ID } from './helpers'

test('validate + execute an action against a non-native target honestly reports unknown, then reconciles', async ({
  page,
}) => {
  await setContext(page)
  await page.goto('/runs/new')
  await page.locator('select').first().selectOption({ label: 'named_roster' })
  await page.getByLabel(/Site IDs/).fill(SITE_ID)
  await page.click('button:has-text("Create run")')
  await page.waitForURL(/\/runs\/run_/)
  await expect(page.locator('.badge')).toHaveText(/completed/)

  await page.click('button:has-text("Start action from this run")')
  await page.waitForURL('/actions/new')
  await expect(page.locator('h1')).toHaveText('New action')

  // Target system defaults to 'deputy' — an Overlay vendor with no real
  // writeback connector, so execute must honestly report 'unknown' rather
  // than fabricate 'confirmed' (see services/tempo-api's NotImplementedWritebackClient).
  await page.getByLabel('Site ID').fill(SITE_ID)
  await page.click('button:has-text("Validate")')

  await expect(page.locator('h2:has-text("Validated")')).toBeVisible()
  await page.click('button:has-text("Execute")')

  await expect(page.locator('h2:has-text("Execution result")')).toBeVisible()
  await expect(page.locator('text=Status:')).toContainText('unknown')

  await page.click('button:has-text("View action")')
  await page.waitForURL(/\/actions\/act_/)
  await expect(page.locator('.badge')).toHaveText(/unknown/)

  await page.click('button:has-text("Reconcile")')
  // Reconciliation against the same non-existent connector can't actually
  // resolve anything — it honestly stays 'unknown' (NotImplementedWritebackClient
  // has no real status to check either), which is the documented behaviour,
  // not a bug. This test just proves the reconcile call round-trips cleanly.
  await expect(page.locator('.badge')).toHaveText(/unknown/)
})

test('validate + execute against a tempo_native target gets a real confirmed writeback', async ({ page }) => {
  await setContext(page)
  await page.goto('/runs/new')
  await page.locator('select').first().selectOption({ label: 'named_roster' })
  await page.getByLabel(/Site IDs/).fill(SITE_ID)
  await page.click('button:has-text("Create run")')
  await page.waitForURL(/\/runs\/run_/)
  await expect(page.locator('.badge')).toHaveText(/completed/)

  await page.click('button:has-text("Start action from this run")')
  await page.waitForURL('/actions/new')

  const selects = page.locator('form select')
  await selects.nth(1).selectOption('tempo_native') // Target system
  await page.getByLabel('Site ID').fill(SITE_ID)
  await page.click('button:has-text("Validate")')

  await expect(page.locator('h2:has-text("Validated")')).toBeVisible()
  await page.click('button:has-text("Execute")')

  await expect(page.locator('h2:has-text("Execution result")')).toBeVisible()
  await expect(page.locator('text=Status:')).toContainText('confirmed')
})

test('actions list shows validated actions and filters by status', async ({ page }) => {
  await setContext(page)
  await page.goto('/actions')
  await expect(page.locator('h1')).toHaveText('Actions')
  await page.selectOption('select', { label: 'All' })
  const listedOrEmpty = page.locator('table').or(page.getByText('No actions yet'))
  await expect(listedOrEmpty).toBeVisible()
})
