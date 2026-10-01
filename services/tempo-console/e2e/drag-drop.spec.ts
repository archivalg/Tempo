import { expect, test, type Page } from '@playwright/test'

// Drag a shift to another worker/day; the server re-validates; Undo restores it. Uses the week after next so it cannot collide with workflow.spec.
async function signIn(p: Page, persona: RegExp) {
  await p.goto('/')
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()
  if (await p.getByRole('button', { name: 'Sign out' }).isVisible()) { await p.getByRole('button', { name: 'Sign out' }).click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  await p.getByRole('button', { name: persona }).click()
  await expect(p.getByRole('button', { name: 'Sign out' })).toBeVisible()
}
const mondayAfterNext = () => { const d = new Date(); d.setUTCDate(d.getUTCDate() + ((8 - d.getUTCDay()) % 7 || 7) + 7); return d.toISOString().slice(0, 10) }

test('planner drags a shift to another worker and day, the server re-checks, and Undo puts it back', async ({ page }) => {
  await signIn(page, /Demo Planner/)
  await page.goto(`/roster?start=${mondayAfterNext()}`)
  await page.getByRole('button', { name: 'Generate draft from forecast' }).click()
  await expect(page.locator('.tp-shift').first()).toBeVisible({ timeout: 120_000 })

  const src = page.locator('.tp-shift').first()
  const srcCell = src.locator('xpath=ancestor::td')
  const rowIdx = await srcCell.evaluate((td) => (td.parentElement as HTMLTableRowElement).sectionRowIndex)
  const colIdx = await srcCell.evaluate((td) => (td as HTMLTableCellElement).cellIndex)
  const label = (await src.getAttribute('aria-label'))!
  const countOf = (l: string) => page.locator('.tp-shift').evaluateAll((els, x) => els.filter((e) => e.getAttribute('aria-label') === x).length, l)
  const before = await countOf(label)
  const target = page.locator('tbody tr').nth(rowIdx + 1).locator('td').nth(colIdx === 7 ? colIdx - 1 : colIdx + 1)
  await src.dragTo(target)
  await expect(page.getByRole('status').filter({ hasText: 'Moved' })).toBeVisible()
  await expect(page.getByRole('status')).toContainText('server re-checked')
  expect(await countOf(label)).toBe(before - 1)   // that worker's shift left its cell (the label is not unique across days, so compare counts)
  await page.screenshot({ path: '../../docs/screenshots/roster-drag-drop.png', fullPage: true })

  await page.getByRole('button', { name: 'Undo' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Moved' })).toHaveCount(0)
  await expect.poll(() => countOf(label)).toBe(before)   // Undo put it back
})

test('an analyst cannot drag shifts', async ({ page }) => {
  await signIn(page, /Demo Analyst/)
  await page.goto(`/roster?start=${mondayAfterNext()}`)
  await expect(page.locator('.tp-shift').first()).toBeVisible()
  await expect(page.locator('.tp-shift[draggable="true"]')).toHaveCount(0)
})
