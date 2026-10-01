import { expect, test, type Page } from '@playwright/test'

// Roadmap M1 in a real browser: a customer loads workload totals from a spreadsheet with their own column names, sees what would happen,
// loads the good rows, cannot double-load the same file, undoes it, and creates an API credential.
async function signIn(p: Page, persona: RegExp) {
  await p.goto('/')
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()
  if (await p.getByRole('button', { name: 'Sign out' }).isVisible()) { await p.getByRole('button', { name: 'Sign out' }).click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  const out = p.getByRole('button', { name: 'Sign out' })
  for (let attempt = 0; attempt < 3 && !(await out.isVisible()); attempt++) {
    await p.getByRole('button', { name: persona }).click()
    await out.waitFor({ timeout: 8000 }).catch(() => undefined)
  }
  await expect(out).toBeVisible()
}

const CSV = [
  'Location,Task,Date,Period,Quantity',
  'syd_dc_02,picking,2026-06-01,day,4100',
  'syd_dc_02,picking,2026-06-02,day,4250',
  'syd_dc_02,welding,2026-06-03,day,10',          // no work standard: rejected with a plain reason
  'syd_dc_02,picking,2026-06-04,day,4300',
].join('\n')

test('load workload totals from a spreadsheet with your own column names, then undo', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/data')
  await expect(page.getByRole('region', { name: 'Setup checklist' })).toBeVisible()
  await page.getByRole('tab', { name: 'Load data' }).click()
  await page.getByRole('button', { name: /Workload totals/ }).click()
  const [tpl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Download the template/ }).click()])
  expect(tpl.suggestedFilename()).toBe('tempo-template-bulk.csv')

  await page.locator('input[type=file]').setInputFiles({ name: 'sydney-june.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) })
  await expect(page.getByLabel('Column for site')).toHaveValue('Location')         // matched from a synonym, not by guesswork
  await expect(page.getByLabel('Column for units')).toHaveValue('Quantity')
  await page.getByRole('button', { name: 'Check the file' }).click()
  const result = page.getByRole('region', { name: 'Check result' })
  await expect(result).toContainText('Rejected')
  await expect(page.getByRole('table', { name: 'Rejected rows' })).toContainText('no work standard')
  await expect(result.getByRole('button', { name: /^Load 3 rows$/ })).toBeDisabled()          // not silently partial
  await page.screenshot({ path: '../../docs/screenshots/data-import-preview.png', fullPage: true })
  const [bad] = await Promise.all([page.waitForEvent('download'), result.getByRole('button', { name: /Download rejected rows/ }).click()])
  expect(bad.suggestedFilename()).toMatch(/^tempo-rejected-rows-/)

  await result.getByRole('button', { name: /Load only the 3 accepted rows/ }).click()
  await expect(result).toContainText('Loaded')
  await expect(result).toContainText('Only the accepted rows were loaded')

  // the same file again changes nothing
  await result.getByRole('button', { name: 'Load another file' }).click()
  await page.locator('input[type=file]').setInputFiles({ name: 'sydney-june.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) })
  await page.getByRole('button', { name: 'Check the file' }).click()
  await expect(page.getByText('You have already sent this exact file')).toBeVisible()

  // history → open → undo
  await page.getByRole('tab', { name: 'History' }).click()
  await page.getByRole('region', { name: 'Load history' }).getByRole('button', { name: 'Open' }).first().click()
  await page.getByRole('dialog').getByRole('button', { name: 'Undo this load' }).click()
  await expect(page.getByRole('dialog')).toContainText('undone')
  await page.screenshot({ path: '../../docs/screenshots/data-import-history.png' })
})

test('an administrator creates an API credential, sees the secret once, and revokes it', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/data?tab=api')
  await page.getByLabel('Name', { exact: true }).fill('E2E feed')
  await page.getByRole('button', { name: 'Create credential' }).click()
  const secret = page.getByLabel('New API secret')
  await expect(secret).toContainText('tsc_')
  await page.reload()
  await expect(page.getByLabel('New API secret')).toHaveCount(0)                      // never shown again
  const row = page.getByRole('table', { name: 'Credentials' }).locator('tr', { hasText: 'E2E feed' }).first()
  await expect(row).toContainText('tsc_')
  await row.getByRole('button', { name: 'Revoke' }).click()
  await expect(row).toContainText('revoked')
})

test('people without import permission do not see the Data page', async ({ page }) => {
  await signIn(page, /Demo Planner/)
  await expect(page.getByRole('link', { name: 'Data', exact: true })).toHaveCount(0)
})
