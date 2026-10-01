import { expect, test, type Page } from '@playwright/test'

// A planner adjusts demand with a reason and expiry; the forecast shows it as adjusted; it is revoked and the model's number returns.
async function signIn(p: Page, persona: RegExp) {
  await p.goto('/')
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()
  if (await p.getByRole('button', { name: 'Sign out' }).isVisible()) { await p.getByRole('button', { name: 'Sign out' }).click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  await p.getByRole('button', { name: persona }).click()
  await expect(p.getByRole('button', { name: 'Sign out' })).toBeVisible()
}

test('planner adjusts demand, sees it flagged, then revokes it; an analyst cannot adjust', async ({ page }) => {
  await signIn(page, /Demo Planner/)
  await page.goto('/demand')
  await page.getByRole('button', { name: 'Adjust demand' }).click()
  const form = page.getByRole('form', { name: 'New demand adjustment' })
  await form.getByLabel('Percent (+/−)').fill('20')
  await form.getByLabel(/Reason/).fill('Short')
  const exp = new Date(); exp.setUTCDate(exp.getUTCDate() + 14)
  await form.getByLabel('Expires').fill(exp.toISOString().slice(0, 10))
  await form.getByRole('button', { name: /Save/ }).click()
  await expect(page.getByRole('alert').filter({ hasText: /why|reason/i }).first()).toBeVisible()   // too-short reason is refused with an explanation
  await form.getByLabel(/Reason/).fill('Customer promotion starts midweek')
  await form.getByRole('button', { name: /Save/ }).click()
  const list = page.getByRole('list', { name: 'Adjustments' })
  await expect(list).toContainText('+20%')
  await expect(list).toContainText('Customer promotion starts midweek')
  await expect(page.locator('td .tp-badge', { hasText: 'adjusted' }).first()).toBeVisible()
  await page.screenshot({ path: '../../docs/screenshots/demand-override.png', fullPage: true })

  await list.getByRole('button', { name: 'Revoke' }).click()
  await page.getByLabel('Reason for revoking').fill('Promotion cancelled')
  await page.getByRole('button', { name: 'Confirm revoke' }).click()
  await expect(list).toContainText('revoked')
  await expect(page.locator('td .tp-badge', { hasText: 'adjusted' })).toHaveCount(0)

  await signIn(page, /Demo Analyst/)
  await page.goto('/demand')
  await expect(page.getByRole('heading', { name: 'Manual adjustments' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Adjust demand' })).toHaveCount(0)
})

test('a large adjustment waits for a different approver and only then reaches the forecast', async ({ page }) => {
  await signIn(page, /Demo Planner/)
  await page.goto('/demand')
  await page.getByRole('button', { name: 'Adjust demand' }).click()
  const form = page.getByRole('form', { name: 'New demand adjustment' })
  await form.getByLabel('Percent (+/−)').fill('45')
  await form.getByLabel(/Reason/).fill('Peak sale event confirmed by the customer')
  const exp = new Date(); exp.setUTCDate(exp.getUTCDate() + 10)
  await form.getByLabel('Expires').fill(exp.toISOString().slice(0, 10))
  await form.getByRole('button', { name: /Save/ }).click()
  const list = page.getByRole('list', { name: 'Adjustments' })
  await expect(list).toContainText('pending')
  await expect(list).toContainText('Not applied yet')
  await expect(page.locator('td .tp-badge', { hasText: 'adjusted' })).toHaveCount(0)           // the plan has not moved
  await expect(list.getByRole('button', { name: 'Approve' })).toHaveCount(0)                    // the proposer cannot approve

  await signIn(page, /Demo Ops Manager/)
  await page.goto('/demand')
  await page.getByRole('list', { name: 'Adjustments' }).getByRole('button', { name: 'Approve' }).click()
  await expect(page.getByRole('list', { name: 'Adjustments' })).toContainText('active')
  await expect(page.locator('td .tp-badge', { hasText: 'adjusted' }).first()).toBeVisible()
  await page.getByRole('list', { name: 'Adjustments' }).getByRole('button', { name: 'Revoke' }).click()
  await page.getByLabel('Reason for revoking').fill('Test finished, restoring the model')
  await page.getByRole('button', { name: 'Confirm revoke' }).click()
  await expect(page.locator('td .tp-badge', { hasText: 'adjusted' })).toHaveCount(0)
})
