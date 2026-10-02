import { expect, test, type Page } from '@playwright/test'

// Roadmap M3: an administrator changes the planning limits from the roster board; a planner sees them but cannot change them.
async function signIn(p: Page, persona: RegExp) {
  await p.goto('/')
  const out = p.getByRole('button', { name: 'Sign out' })
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()
  if (await out.isVisible()) { await out.click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  for (let attempt = 0; attempt < 3 && !(await out.isVisible()); attempt++) {
    await p.getByRole('button', { name: persona }).click()
    await out.waitFor({ timeout: 8000 }).catch(() => undefined)
  }
  await expect(out).toBeVisible()
}

test('planning rules: admin saves a new version; planner can read but not change', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/roster')
  await page.getByRole('button', { name: 'Planning rules' }).click()
  const rest = page.getByLabel(/Minimum rest between shifts/)
  await rest.fill('11')
  await page.getByRole('button', { name: 'Save rules' }).click()
  await expect(page.getByText(/Saved\. Applies to rosters generated/)).toBeVisible()
  await page.reload()
  await page.getByRole('button', { name: 'Planning rules' }).click()
  await expect(page.getByLabel(/Minimum rest between shifts/)).toHaveValue('11')
  await page.getByLabel(/Minimum rest between shifts/).fill('10')   // put the demo back
  await page.getByRole('button', { name: 'Save rules' }).click()
  await expect(page.getByText(/Saved\. Applies/)).toBeVisible()
  await signIn(page, /Demo Planner/)
  await page.goto('/roster')
  await page.getByRole('button', { name: 'Planning rules' }).click()
  await expect(page.getByText('Only a tenant administrator can change these.')).toBeVisible()
  await expect(page.getByLabel(/Minimum rest between shifts/)).toBeDisabled()
})
