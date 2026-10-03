import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'

// Roadmap M2 in a real browser, on the seeded (synthetic) Ensemble tenant: kiosk break cycle, supervisor day list, approval, payroll file, rules, badge roster.
const PERSONA: Record<string, RegExp> = { ops: /Demo Ops Manager/, supervisor: /Demo Supervisor/, admin: /Demo Tenant Admin/, analyst: /Demo Analyst/ }
async function signIn(p: Page, who: keyof typeof PERSONA) {
  await p.goto('/')
  const out = p.getByRole('button', { name: 'Sign out' })
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()
  if (await out.isVisible()) { await out.click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  for (let attempt = 0; attempt < 3 && !(await out.isVisible()); attempt++) {
    await p.getByRole('button', { name: PERSONA[who] }).click()
    await out.waitFor({ timeout: 8000 }).catch(() => undefined)
  }
  await expect(out).toBeVisible()
}

test.describe.serial('internal time and attendance', () => {
  test('admin sets the site rules and sees the badge/PIN roster; a supervisor cannot', async ({ page }) => {
    await signIn(page, 'admin')
    await page.goto('/attendance')
    await page.getByRole('tab', { name: 'Rules' }).click()
    await page.getByLabel('Breaks').selectOption('unpaid')
    await page.getByLabel('Round payable hours to').selectOption('15')
    await page.getByRole('button', { name: 'Save rules' }).click()
    await expect(page.getByText('Saved').first()).toBeVisible()
    await page.reload()
    await page.getByRole('tab', { name: 'Rules' }).click()
    await expect(page.getByLabel('Round payable hours to')).toHaveValue('15')
    await page.getByLabel('Round payable hours to').selectOption('0')   // leave the demo site without rounding
    await page.getByRole('button', { name: 'Save rules' }).click()
    await expect(page.getByText('Saved').first()).toBeVisible()
    await page.getByRole('tab', { name: 'Badges & PINs' }).click()
    await expect(page.getByRole('columnheader', { name: 'Badge no.' })).toBeVisible()
    await expect(page.getByText(/argon2/i)).toHaveCount(0)
    await signIn(page, 'supervisor')
    await page.goto('/attendance')
    await expect(page.getByRole('tab', { name: 'Badges & PINs' })).toHaveCount(0)
    await page.getByRole('tab', { name: 'Rules' }).click()
    await expect(page.getByText('Only a tenant administrator can change these rules.')).toBeVisible()
  })

  test('worker clocks in, takes a break and clocks out at the kiosk; the supervisor approves; payroll CSV carries it', async ({ page, browser }) => {
    const m = readFileSync(`${homedir()}/.config/tempo-demo/kiosk.txt`, 'utf8').match(/worker_no=(\d+) pin=(\d+)/m)!
    const [workerNo, pin] = [m[1], m[2]]
    await signIn(page, 'admin')
    await page.goto('/admin')
    await page.getByLabel('Device name').fill(`E2E attendance kiosk ${Date.now()}`)
    await page.getByRole('button', { name: /Create & get enrolment code/ }).click()
    const code = (await page.locator('code').first().innerText()).trim()

    const ctx = await browser.newContext({ viewport: { width: 1024, height: 768 } })
    const k = await ctx.newPage()
    await k.goto('/kiosk')
    await k.getByLabel('Enrolment code').fill(code)
    await k.getByRole('button', { name: 'Enrol device' }).click()
    await expect(k.getByText('Clock in or out')).toBeVisible()
    // the kiosk shows manager screens to nobody: its device credential is not a console session
    await k.goto('/attendance')
    await expect(k.getByRole('heading', { name: 'Attendance & timesheets' })).toHaveCount(0)
    await k.goto('/kiosk')

    const identify = async () => {
      await k.getByRole('button', { name: /^Worker no\./ }).click()
      for (const d of workerNo) await k.getByRole('button', { name: d, exact: true }).click()
      await k.getByRole('button', { name: /^PIN:/ }).click()
      for (const d of pin) await k.getByRole('button', { name: d, exact: true }).click()
      await k.getByRole('button', { name: 'Continue' }).click()
      await expect(k.getByText(/Hello, worker/)).toBeVisible()
    }
    await identify()
    if (await k.getByRole('button', { name: 'Clock out' }).isVisible()) {   // leave a clean state if an earlier run left this worker clocked in
      if (await k.getByRole('button', { name: 'End break' }).isVisible()) { await k.getByRole('button', { name: 'End break' }).click(); await expect(k.getByText(/Back from break at/)).toBeVisible(); await k.getByRole('button', { name: /^Worker no\./ }).waitFor({ timeout: 9000 }); await identify() }
      await k.getByRole('button', { name: 'Clock out' }).click(); await expect(k.getByText(/Clocked out at/)).toBeVisible(); await k.getByRole('button', { name: /^Worker no\./ }).waitFor({ timeout: 9000 }); await identify()
    }
    await expect(k.getByText('You are not clocked in.')).toBeVisible()
    await expect(k.getByRole('button', { name: 'Start break' })).toHaveCount(0)   // not offered until clocked in
    await k.getByRole('button', { name: 'Clock in' }).click()
    await expect(k.getByText(/Clocked in at \d\d:\d\d/)).toBeVisible()
    await k.getByRole('button', { name: /^Worker no\./ }).waitFor({ timeout: 9000 })   // returns to the start screen by itself
    await identify()
    await expect(k.getByText('You are clocked in.')).toBeVisible()
    await k.getByRole('button', { name: 'Start break' }).click()
    await expect(k.getByText(/Break started at/)).toBeVisible()
    await k.getByRole('button', { name: /^Worker no\./ }).waitFor({ timeout: 9000 })
    await identify()
    await expect(k.getByText('You are on a break.')).toBeVisible()
    await expect(k.getByRole('button', { name: 'Start break' })).toHaveCount(0)
    await k.getByRole('button', { name: 'End break' }).click()
    await expect(k.getByText(/Back from break at/)).toBeVisible()
    await k.getByRole('button', { name: /^Worker no\./ }).waitFor({ timeout: 9000 })
    await identify()
    await k.getByRole('button', { name: 'Clock out' }).click()
    await expect(k.getByText(/Clocked out at \d\d:\d\d/)).toBeVisible()
    await ctx.close()

    // supervisor: the day list shows the worker, the timesheet shows worked / break separately, approval makes it payable
    await signIn(page, 'supervisor')
    await page.goto('/attendance')
    await expect(page.getByRole('table')).toBeVisible()
    await expect(page.getByText('Late means more than')).toBeVisible()
    await page.getByRole('tab', { name: 'Timesheets' }).click()
    await expect(page.getByRole('columnheader', { name: 'Break h' })).toBeVisible()
    await expect(page.getByRole('columnheader', { name: 'Payable h' })).toBeVisible()
    const row = page.locator('tbody tr').filter({ hasText: 'Pending' }).filter({ hasNot: page.locator('.tp-badge', { hasText: /Open|Correction|No clock-out/ }) }).first()
    const who = (await row.locator('td').nth(1).innerText()).split('\n')[0]
    await row.getByRole('button', { name: 'Open' }).click()
    await page.getByText('History: punches, corrections and revisions').click()
    await expect(page.getByRole('dialog')).toContainText('clock in')
    await page.getByRole('button', { name: 'Approve timesheet as punched' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    // reopening is deliberate: it needs a reason, records a revision, and takes the timesheet out of payroll until it is approved again
    const mine = () => page.locator('tbody tr').filter({ hasText: who })
    await mine().filter({ hasText: 'Approved' }).first().getByRole('button', { name: 'Open' }).click()
    await expect(page.getByRole('button', { name: /Reopen — records revision 2/ })).toBeDisabled()
    await page.getByLabel(/Reason \(at least 10 characters\)/).fill('Payroll queried the break length')
    await page.getByRole('button', { name: /Reopen — records revision 2/ }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await mine().filter({ hasText: 'Pending' }).first().getByRole('button', { name: 'Open' }).click()
    await page.getByRole('button', { name: 'Approve timesheet as punched' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(mine().filter({ hasText: 'rev 2' }).first()).toBeVisible()

    await signIn(page, 'ops')
    await page.goto('/attendance')
    await page.getByRole('tab', { name: 'Timesheets' }).click()
    const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Payroll CSV/ }).click()])
    expect(dl.suggestedFilename()).toMatch(/^tempo-payroll-timesheets-.*\.csv$/)
    const text = readFileSync(await dl.path()!, 'utf8')
    expect(text).toContain('employee_no,worker_id,name,work_date')
    expect(text).toContain('Hours only: no award or pay interpretation')
    expect(text).toMatch(/not yet approved and are NOT included/)

    await signIn(page, 'analyst')
    await page.goto('/attendance')
    await page.getByRole('tab', { name: 'Timesheets' }).click()
    await expect(page.getByRole('button', { name: /Payroll CSV/ })).toHaveCount(0)
  })

  test('site fence and location: a kiosk outside the fence is refused, one inside clocks, and the rule can be turned off', async ({ page, browser }) => {
    const m = readFileSync(`${homedir()}/.config/tempo-demo/kiosk.txt`, 'utf8').match(/worker_no=(\d+) pin=(\d+)\s*\nworker_no=(\d+) pin=(\d+)/m)!
    const [workerNo, pin] = [m[3], m[4]]
    await signIn(page, 'admin')
    await page.goto('/attendance')
    await page.getByRole('tab', { name: 'Rules' }).click()
    await page.getByLabel('Latitude').fill('-37.8136')
    await page.getByLabel('Longitude').fill('144.9631')
    await page.getByLabel(/^Radius/).fill('200')
    await page.getByRole('button', { name: 'Save geofence' }).click()
    await expect(page.getByText('Geofence saved.')).toBeVisible()
    await page.getByLabel('Location at each punch').selectOption('require')
    await page.getByRole('button', { name: 'Save rules' }).click()
    await expect(page.getByText('Saved').first()).toBeVisible()
    await page.goto('/admin')
    await page.getByLabel('Device name').fill(`E2E fence kiosk ${Date.now()}`)
    await page.getByRole('button', { name: /Create & get enrolment code/ }).click()
    const code = (await page.locator('code').first().innerText()).trim()

    const at = async (geo: { latitude: number; longitude: number }, enrolCode?: string) => {
      const ctx = await browser.newContext({ viewport: { width: 1024, height: 768 }, geolocation: geo, permissions: ['geolocation'] })
      const k = await ctx.newPage()
      await k.goto('/kiosk')
      if (enrolCode) { await k.getByLabel('Enrolment code').fill(enrolCode); await k.getByRole('button', { name: 'Enrol device' }).click() }
      await expect(k.getByText('Clock in or out')).toBeVisible()
      await k.getByRole('button', { name: /^Worker no\./ }).click()
      for (const d of workerNo) await k.getByRole('button', { name: d, exact: true }).click()
      await k.getByRole('button', { name: /^PIN:/ }).click()
      for (const d of pin) await k.getByRole('button', { name: d, exact: true }).click()
      await k.getByRole('button', { name: 'Continue' }).click()
      await expect(k.getByText('This site checks the kiosk’s location when you clock.')).toBeVisible()
      return { k, ctx }
    }
    const far = await at({ latitude: -37.9, longitude: 145.2 }, code)
    const credential = await far.k.evaluate(() => localStorage.getItem('tempo.kiosk.device'))
    const clockAction = far.k.getByRole('button', { name: /^(Clock in|Clock out)$/ })
    await clockAction.click()
    await expect(far.k.getByRole('alert')).toContainText('not recorded')
    await far.ctx.close()

    const near = await browser.newContext({ viewport: { width: 1024, height: 768 }, geolocation: { latitude: -37.8137, longitude: 144.9632 }, permissions: ['geolocation'] })
    await near.addInitScript((c) => localStorage.setItem('tempo.kiosk.device', c as string), credential)
    const k = await near.newPage()
    await k.goto('/kiosk')
    await k.getByRole('button', { name: /^Worker no\./ }).click()
    for (const d of workerNo) await k.getByRole('button', { name: d, exact: true }).click()
    await k.getByRole('button', { name: /^PIN:/ }).click()
    for (const d of pin) await k.getByRole('button', { name: d, exact: true }).click()
    await k.getByRole('button', { name: 'Continue' }).click()
    await k.getByRole('button', { name: /^(Clock in|Clock out)$/ }).click()
    await expect(k.getByText(/Clocked (in|out) at \d\d:\d\d/)).toBeVisible()
    await near.close()

    // the day list and history carry the evidence; then the rule goes back to off for the other tests
    await page.goto('/attendance')
    await page.getByRole('tab', { name: 'Rules' }).click()
    await page.getByLabel('Location at each punch').selectOption('off')
    await page.getByRole('button', { name: 'Save rules' }).click()
    await expect(page.getByText('Saved').first()).toBeVisible()
  })

  test('people: an administrator changes a badge number, edits skills, and makes someone inactive and active again', async ({ page }) => {
    await signIn(page, 'admin')
    await page.goto('/attendance?view=badges')
    await expect(page.getByRole('columnheader', { name: 'Skills' })).toBeVisible()
    const row = page.locator('tbody tr').filter({ hasText: 'Active' }).first()
    const who = (await row.locator('td').first().innerText()).trim()
    const mine = () => page.locator('tbody tr').filter({ hasText: who })
    await mine().getByRole('button', { name: /^(Change|Set)$/ }).click()
    const badge = String(900000 + Math.floor(Math.random() * 99999))
    await page.getByLabel(/New badge number/).fill(badge)
    await page.getByRole('button', { name: 'Save', exact: true }).click()
    await expect(mine()).toContainText(badge)
    await mine().getByRole('button', { name: /Edit skills/ }).click()
    await page.getByLabel('Add a skill').fill('e2e_skill')
    await page.getByRole('button', { name: 'Add', exact: true }).click()
    await expect(page.getByRole('dialog')).toContainText('e2e_skill')
    await page.getByRole('button', { name: 'Remove e2e_skill' }).click()
    await expect(page.getByRole('dialog').getByText('e2e_skill')).toHaveCount(0)
    await page.keyboard.press('Escape')
    page.once('dialog', (d) => void d.accept())
    await mine().getByRole('button', { name: 'Make inactive' }).click()
    await expect(mine()).toContainText('inactive')
    await mine().getByRole('button', { name: 'Reactivate' }).click()
    await expect(mine()).toContainText('Active')
  })
})
