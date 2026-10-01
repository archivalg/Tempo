import { expect, test, type Page } from '@playwright/test'

// The bell: an approver is told when a roster is submitted, opens it from the bell, and the unread count clears.
async function signIn(p: Page, persona: RegExp) {
  await p.goto('/')
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()
  if (await p.getByRole('button', { name: 'Sign out' }).isVisible()) { await p.getByRole('button', { name: 'Sign out' }).click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  await p.getByRole('button', { name: persona }).click()
  await expect(p.getByRole('button', { name: 'Sign out' })).toBeVisible()
}
const weekIn = (weeks: number) => { const d = new Date(); d.setUTCDate(d.getUTCDate() + weeks * 7); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d.toISOString().slice(0, 10) }
const bell = (p: Page) => p.getByRole('button', { name: /^Notifications, \d+ unread$/ })

test('planner submits; the ops manager sees it in the bell, follows it to Approvals, and marks all read', async ({ page }) => {
  const week = weekIn(3)
  await signIn(page, /Demo Planner/)
  await page.goto(`/roster?start=${week}`)
  await page.getByRole('button', { name: 'Generate draft from forecast' }).click()
  await expect(page.locator('.tp-shift').first()).toBeVisible({ timeout: 120_000 })
  await page.getByRole('button', { name: 'Submit for approval' }).click()
  await expect(page.getByText('Awaiting a different approver')).toBeVisible()

  await signIn(page, /Demo Ops Manager/)
  await expect(bell(page)).toBeVisible()
  await bell(page).click()
  const panel = page.getByRole('region', { name: 'Notifications' })
  await expect(panel).toContainText(`Roster awaiting approval — week of ${week}`)
  await page.screenshot({ path: '../../docs/screenshots/notifications-bell.png' })
  await panel.getByRole('button', { name: new RegExp(`week of ${week}`) }).first().click()
  await expect(page).toHaveURL(/\/approvals/)
  await bell(page).click()
  const all = page.getByRole('button', { name: 'Mark all read' })
  if (await all.isEnabled()) await all.click()   // already clear if following the notice was the only unread one
  await expect(page.getByRole('button', { name: 'Notifications, 0 unread' })).toBeVisible()
})
