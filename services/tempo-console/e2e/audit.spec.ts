import { expect, test, type Page } from '@playwright/test'

async function signIn(p: Page, persona: RegExp) {
  await p.goto('/')
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()
  if (await p.getByRole('button', { name: 'Sign out' }).isVisible()) { await p.getByRole('button', { name: 'Sign out' }).click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  await p.getByRole('button', { name: persona }).click()
  await expect(p.getByRole('button', { name: 'Sign out' })).toBeVisible()
}

test('a tenant admin reads and filters the audit log; others do not get the page', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.getByRole('link', { name: 'Audit log' }).click()
  const table = page.getByRole('region', { name: 'Audit events' })
  await expect(table.locator('tbody tr').first()).toBeVisible()
  await page.getByLabel('Outcome').selectOption('denied')
  await expect(table).toContainText(/denied|No matching events/)
  await page.getByLabel('Outcome').selectOption('')
  await page.getByLabel('Action').selectOption('audit.view')
  await expect(table.locator('tbody tr').first()).toContainText('audit.view')
  await page.screenshot({ path: '../../docs/screenshots/audit-log.png', fullPage: true })
  await signIn(page, /Demo Planner/)
  await expect(page.getByRole('link', { name: 'Audit log' })).toHaveCount(0)
})
