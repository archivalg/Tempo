import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'

// CSV export from the three report screens, in a real browser, as a role that may export and one that may not.
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

test('ops manager downloads the variance, timesheet and demand files; analyst has no export control', async ({ page }) => {
  await signIn(page, /Demo Ops Manager/)
  for (const [path, file] of [['/reports', 'variance'], ['/attendance', 'timesheets'], ['/demand', 'demand']] as const) {
    await page.goto(path)
    const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Export CSV/ }).click()])
    expect(dl.suggestedFilename()).toMatch(new RegExp(`^tempo-${file}-.*\\.csv$`))
    const text = readFileSync(await dl.path()!, 'utf8')
    expect(text.startsWith('# Tempo ')).toBeTruthy()
    expect(text).toContain(file === 'variance' ? 'ESTIMATE' : file === 'timesheets' ? 'worker,role' : 'activity')
  }
  await signIn(page, /Demo Analyst/)
  await page.goto('/reports')
  await expect(page.getByRole('heading', { name: /Insights & Reports/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Export CSV/ })).toHaveCount(0)
})
