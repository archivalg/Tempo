import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

// Overlay site (Sydney): adjust the live roster, approve, publish, then hand it over by file and attest it was loaded.
async function signIn(p: Page, persona: RegExp) {
  await p.goto('/')
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()
  if (await p.getByRole('button', { name: 'Sign out' }).isVisible()) { await p.getByRole('button', { name: 'Sign out' }).click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  const out = p.getByRole('button', { name: 'Sign out' })
  for (let attempt = 0; attempt < 3 && !(await out.isVisible()); attempt++) {   // a sign-in click can be lost while the picker re-renders under load
    await p.getByRole('button', { name: persona }).click()
    await out.waitFor({ timeout: 8000 }).catch(() => undefined)
  }
  await expect(out).toBeVisible()
}
const monday = () => { const d = new Date(); d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7)); return d.toISOString().slice(0, 10) }

test('overlay hand-over: publish → download file → attest; the screen never says the vendor confirmed', async ({ page }) => {
  const url = `/roster?start=${monday()}&site=syd_dc_02`
  await signIn(page, /Demo Tenant Admin/)
  await page.goto(url)
  await page.getByRole('button', { name: 'Start from the live roster' }).click()
  await expect(page.getByRole('list', { name: 'Roster progress' })).toContainText('Draft')
  await page.getByRole('button', { name: 'Submit for approval' }).click()
  await expect(page.getByText('Awaiting a different approver')).toBeVisible()

  await signIn(page, /Demo Ops Manager/)
  await page.goto(url)
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Approve', exact: true }).click()
  await page.getByRole('button', { name: 'Publish roster' }).click()
  await page.getByRole('dialog').getByRole('button', { name: 'Publish now' }).click()

  const card = page.getByRole('region', { name: 'Hand-over to the external system' })
  await expect(card).toContainText('Not handed over yet')
  const [dl] = await Promise.all([page.waitForEvent('download'), card.getByRole('button', { name: /Download roster file/ }).click()])
  expect(readFileSync(await dl.path()!, 'utf8')).toContain('worker_ref')
  await expect(card).toContainText('File downloaded')
  await card.getByLabel(/Reference in the other system/).fill('IMP-2026-0042')
  await card.getByRole('button', { name: /I loaded this file/ }).click()
  await expect(card).toContainText('confirmed by a person (not by the vendor)')
  await expect(card).not.toContainText('Confirmed by the vendor')
  await page.screenshot({ path: '../../docs/screenshots/overlay-handoff.png', fullPage: true })
})
