import { expect, test } from '@playwright/test'
import { setContext, SITE_ID } from './helpers'

test('creates a run from the console and views its explanation', async ({ page }) => {
  await setContext(page)
  await page.goto('/runs')
  await expect(page.locator('h1')).toHaveText('Runs')

  await page.click('a.button:has-text("New run")')
  await expect(page.locator('h1')).toHaveText('New run')

  await page.selectOption('select', { label: 'demand_forecast' })
  await page.getByLabel(/Site IDs/).fill(SITE_ID)
  await page.click('button:has-text("Create run")')

  await page.waitForURL(/\/runs\/run_/)
  await expect(page.locator('h1')).toContainText('Run run_')
  await expect(page.locator('.badge')).toHaveText(/completed/)

  await expect(page.locator('text=Confidence:')).toBeVisible()
  await expect(page.locator('h2:has-text("Result")')).toBeVisible()
  await expect(page.locator('.json-block').last()).toContainText('forecast')
})

test('runs list filters by run type', async ({ page }) => {
  await setContext(page)
  await page.goto('/runs')
  await page.selectOption('select', { label: 'demand_forecast' })
  await page.waitForTimeout(300)
  const rows = page.locator('table tbody tr')
  const count = await rows.count()
  for (let i = 0; i < count; i++) {
    // td(0) is the comparison-selection checkbox, td(1) is the run ID link.
    await expect(rows.nth(i).locator('td').nth(2)).toHaveText('demand_forecast')
  }
})
