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

test('availability & leave: a planner records leave, sees it listed, and removes it; shifts are editable by an administrator', async ({ page }) => {
  await signIn(page, /Demo Planner/)
  await page.goto('/roster')
  await page.getByRole('button', { name: /Availability & leave/ }).click()
  const dlg = page.getByRole('dialog')
  await dlg.getByLabel('Worker').selectOption({ index: 1 })
  const d = new Date(); d.setDate(d.getDate() + 2)
  const day = d.toISOString().slice(0, 10)
  await dlg.getByLabel(/^From/).fill(`${day}T08:00`)
  await dlg.getByLabel(/^To/).fill(`${day}T16:00`)
  await dlg.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(dlg.getByText('Leave').first()).toBeVisible()
  await dlg.getByRole('button', { name: /^Remove Leave/ }).first().click()
  await expect(dlg.getByText('No unavailability or leave in this period')).toBeVisible()
  await page.keyboard.press('Escape')

  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/roster')
  await page.getByRole('button', { name: 'Planning rules' }).click()
  await expect(page.getByRole('group', { name: 'Shift 1' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add a shift' })).toBeVisible()
})

test('a report day links to that day\'s attendance list', async ({ page }) => {
  await signIn(page, /Demo Ops Manager/)
  await page.goto('/reports')
  await page.locator('tbody a[href^="/attendance?view=today&date="]').first().click()
  await expect(page.getByRole('heading', { name: 'Attendance & timesheets' })).toBeVisible()
  await expect(page.getByText('Late means more than')).toBeVisible()
})

test('administration shows the organisation\'s plan state honestly (the demo tenant has no plan recorded)', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/admin')
  await expect(page.getByText('No plan recorded')).toBeVisible()
  await expect(page.getByText(/no commercial limits are applied/)).toBeVisible()
})
