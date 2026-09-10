import { expect, test } from '@playwright/test'
import { setContext, SITE_ID } from './helpers'

async function createDemandForecastRun(page: import('@playwright/test').Page): Promise<string> {
  await page.goto('/runs/new')
  await page.locator('select').first().selectOption({ label: 'demand_forecast' })
  await page.getByLabel(/Site IDs/).fill(SITE_ID)
  await page.click('button:has-text("Create run")')
  await page.waitForURL(/\/runs\/run_/)
  await expect(page.locator('.badge')).toHaveText(/completed/)
  return page.url().split('/').pop() as string
}

test('selecting two runs from the list and comparing shows their KPIs side by side', async ({ page }) => {
  await setContext(page)
  const firstRunId = await createDemandForecastRun(page)
  const secondRunId = await createDemandForecastRun(page)

  await page.goto('/runs')
  await page.selectOption('select', { label: 'demand_forecast' })

  await page.locator(`input[aria-label="Select ${firstRunId} for comparison"]`).check()
  await page.locator(`input[aria-label="Select ${secondRunId} for comparison"]`).check()
  await expect(page.locator('button:has-text("Compare selected")')).toHaveText('Compare selected (2)')
  await page.click('button:has-text("Compare selected")')

  await page.waitForURL('/runs/compare')
  await expect(page.locator('h1')).toHaveText('Compare runs')
  await page.click('button:has-text("Compare")')

  const table = page.locator('table')
  await expect(table.locator('th', { hasText: firstRunId })).toBeVisible()
  await expect(table.locator('th', { hasText: secondRunId })).toBeVisible()
  await expect(table).toContainText('activities_forecast')
  await expect(table).toContainText('horizon_buckets')
})

test('comparing fewer than two runs is rejected by the backend', async ({ page }) => {
  await setContext(page)
  await page.goto('/runs/compare')
  await page.getByLabel(/Run IDs/).fill('run_only_one')
  await page.click('button:has-text("Compare")')
  await expect(page.locator('.error-banner')).toBeVisible()
})
