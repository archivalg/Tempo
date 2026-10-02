import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'

// demand → roster → approval → attendance → variance, in a real browser, on the seeded (synthetic) Ensemble tenant.
const SHOTS = '../../docs/screenshots'
const shot = (p: Page, name: string, full = false) => p.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: full })
const PERSONA: Record<string, RegExp> = { planner: /Demo Planner/, ops: /Demo Ops Manager/, supervisor: /Demo Supervisor/, admin: /Demo Tenant Admin/, analyst: /Demo Analyst/ }

async function signIn(p: Page, who: keyof typeof PERSONA) {
  await p.goto('/')
  const out = p.getByRole('button', { name: 'Sign out' })
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()  // session resolved either way
  if (await out.isVisible()) { await out.click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  await p.getByRole('button', { name: PERSONA[who] }).click()
  await expect(p.getByRole('button', { name: 'Sign out' })).toBeVisible()
}
const nextMonday = () => { const d = new Date(); d.setUTCDate(d.getUTCDate() + ((8 - d.getUTCDay()) % 7 || 7)); return d.toISOString().slice(0, 10) }

test.describe.serial('planning cycle', () => {
  let weekUrl = ''
  let workerA = '', pinA = ''

  test('planner generates a draft for next week, edits, is blocked by a conflict, then submits', async ({ page }) => {
    await signIn(page, 'planner')
    weekUrl = `/roster?start=${nextMonday()}`
    await page.goto(weekUrl)
    await expect(page.getByText('No roster exists for this week yet.')).toBeVisible()
    await shot(page, 'flow-01-roster-empty')
    await page.getByRole('button', { name: 'Generate draft from forecast' }).click()
    await expect(page.getByText('Draft', { exact: true }).first()).toBeVisible({ timeout: 120_000 })
    await expect(page.getByRole('list', { name: 'Roster progress' })).toContainText('Draft')
    await expect(page.locator('.tp-shift').first()).toBeVisible()
    await shot(page, 'flow-02-draft-generated')

    // open a shift, change its zone, save → server re-validates
    await page.locator('.tp-shift').first().click()
    const zone = page.getByLabel('Zone', { exact: true }).last()
    await zone.fill('pick_b')
    await page.getByRole('button', { name: 'Save & re-validate' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()

    // add a deliberately overlapping shift → hard conflict, submit disabled
    const submit = page.getByRole('button', { name: 'Submit for approval' })
    await expect(submit).toBeEnabled()
    await page.locator('.tp-shift').first().click()
    const start = await page.getByLabel(/Starts/).inputValue(), end = await page.getByLabel(/Ends/).inputValue()
    const worker = await page.getByRole('dialog').locator('select').first().inputValue()
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Add shift', exact: true }).click()
    await page.getByRole('dialog').locator('select').first().selectOption(worker)
    await page.getByLabel(/Starts/).fill(start); await page.getByLabel(/Ends/).fill(end)
    await page.getByRole('button', { name: 'Save & re-validate' }).click()
    await expect(page.getByText('Overlap').first()).toBeVisible()
    await expect(submit).toBeDisabled()
    await shot(page, 'flow-03-conflict-blocks-submit')
    // remove the duplicate again (the conflicting shift is flagged) and submit
    await page.locator('.tp-shift.conflict').first().click()
    await page.getByRole('button', { name: 'Remove shift' }).click()
    await expect(submit).toBeEnabled()
    await submit.click()
    await expect(page.getByRole('list', { name: 'Roster progress' })).toContainText('Submitted')
    await expect(page.getByText('Awaiting a different approver')).toBeVisible()
    await shot(page, 'flow-04-submitted')
  })

  test('a different user approves and publishes; reconciliation passes', async ({ page }) => {
    await signIn(page, 'ops')
    await page.goto('/approvals')
    await expect(page.getByRole('table')).toContainText('week of')
    await shot(page, 'flow-05-approvals-inbox')
    await page.getByRole('row').filter({ hasText: `week of ${weekUrl.split('=')[1]}` }).getByRole('button', { name: 'Review' }).click()
    await expect(page.getByRole('dialog')).toContainText('Hard conflicts')
    await shot(page, 'flow-06-approval-impact')
    await page.getByRole('button', { name: 'Approve', exact: true }).click()
    await expect(page.getByRole('row').filter({ hasText: `week of ${weekUrl.split('=')[1]}` }).locator('.tp-step.now')).toHaveText('Approved')
    await page.getByRole('row').filter({ hasText: `week of ${weekUrl.split('=')[1]}` }).getByRole('button', { name: 'Review' }).click()
    await page.getByRole('button', { name: 'Publish now' }).click()
    await page.goto(weekUrl)
    await expect(page.getByRole('list', { name: 'Roster progress' })).toContainText('reconciled')
    await expect(page.getByText('All checks passed')).toBeVisible()
    await page.getByRole('button', { name: 'History' }).click()
    for (const a of ['generated', 'submitted', 'approved', 'published', 'reconciled']) await expect(page.getByRole('dialog')).toContainText(a)
    await shot(page, 'flow-07-published-history')
  })

  test('editing a published roster is only via a copy, and the submitter cannot approve', async ({ page }) => {
    await signIn(page, 'planner')
    await page.goto(weekUrl)
    await expect(page.getByRole('button', { name: 'Submit for approval' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Adjust (copy to new draft)' }).click()
    await page.getByRole('button', { name: 'Create draft' }).click()
    await expect(page.getByRole('list', { name: 'Roster progress' })).toContainText('Draft')
    await page.locator('.tp-shift').first().click()
    await page.getByRole('button', { name: 'Remove shift' }).click()
    await page.getByRole('button', { name: 'Submit for approval' }).click()
    await expect(page.getByText('Awaiting a different approver')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Approve', exact: true })).toHaveCount(0)
  })

  test('kiosk: admin enrols a device; a worker clocks in and out with badge number and PIN', async ({ page, browser }) => {
    const secrets = readFileSync(`${homedir()}/.config/tempo-demo/kiosk.txt`, 'utf8')
    const m = secrets.match(/worker_no=(\d+) pin=(\d+)/)!
    ;[workerA, pinA] = [m[1], m[2]]
    await signIn(page, 'admin')
    await page.goto('/admin')
    await page.getByLabel('Device name').fill(`E2E kiosk ${Date.now()}`)
    await page.getByRole('button', { name: /Create & get enrolment code/ }).click()
    const code = (await page.locator('code').first().innerText()).trim()
    await shot(page, 'flow-08-device-enrolment')

    const ctx = await browser.newContext({ viewport: { width: 1024, height: 768 } })
    const k = await ctx.newPage()
    await k.goto('/kiosk')
    await k.getByLabel('Enrolment code').fill(code)
    await k.getByRole('button', { name: 'Enrol device' }).click()
    await expect(k.getByText('Clock in or out')).toBeVisible()
    const type = async (digits: string) => { for (const d of digits) await k.getByRole('button', { name: d, exact: true }).click() }
    await type(workerA)
    await k.getByRole('button', { name: /^PIN:/ }).click()
    await type('000000')  // wrong PIN first
    await k.getByRole('button', { name: 'Continue' }).click()
    await expect(k.getByRole('alert')).toContainText('Not recognised')
    await k.getByRole('button', { name: /^PIN:/ }).click()
    await k.getByRole('button', { name: 'Clear' }).click()
    await type(pinA)
    await shot(k, 'flow-09-kiosk-keypad')
    await k.getByRole('button', { name: 'Continue' }).click()
    await expect(k.getByText(/Hello, worker/)).toBeVisible()
    await shot(k, 'flow-10-kiosk-confirm')
    const clockOut = k.getByRole('button', { name: 'Clock out' })
    if (await clockOut.isVisible()) { await clockOut.click(); await expect(k.getByText(/Clocked out at/)).toBeVisible() }
    else { await k.getByRole('button', { name: 'Clock in' }).click(); await expect(k.getByText(/Clocked in at/)).toBeVisible() }
    await shot(k, 'flow-11-kiosk-done')
    await ctx.close()
  })

  test('supervisor sees live operations with sources, exceptions and a resolve path', async ({ page }) => {
    await signIn(page, 'supervisor')
    await page.goto('/live')
    await expect(page.getByText('Connected').first()).toBeVisible()
    await expect(page.getByText('Expected', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Exceptions' })).toBeVisible()
    await shot(page, 'flow-12-live-operations', true)
    const item = page.locator('.tp-item').filter({ hasText: /Unrostered punch|Late|Certification/ }).first()
    await item.click()
    await page.getByRole('button', { name: 'Assign to me' }).click()
    await page.locator('textarea').fill('Checked with team lead; handled.')
    await page.getByRole('button', { name: 'Resolve', exact: true }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await shot(page, 'flow-13-exception-resolved')
  })

  test('timesheets: supervisor approves and requests a correction; a second user approves it; variance reflects payable time', async ({ page }) => {
    await signIn(page, 'supervisor')
    await page.goto('/attendance')
    await page.getByRole('tab', { name: 'Timesheets' }).click()
    await expect(page.getByText('Awaiting approval').first()).toBeVisible()
    await page.getByRole('button', { name: 'Awaiting approval' }).click()
    const before = await page.locator('.tp-kpi').filter({ hasText: 'Approved (payable)' }).locator('.val').innerText()
    // an approvable row: closed session, not already corrected/pending correction
    const approvable = page.locator('tbody tr').filter({ hasText: 'Pending' }).filter({ hasNot: page.locator('.tp-badge', { hasText: /Open|Correction/ }) }).first()
    await approvable.getByRole('button', { name: 'Open' }).click()
    await page.getByRole('button', { name: 'Approve timesheet as punched' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()
    await expect(page.locator('.tp-kpi').filter({ hasText: 'Approved (payable)' }).locator('.val')).toHaveText(String(Number(before) + 1))
    await shot(page, 'flow-14-timesheets')

    // a pending correction (seeded, requested by the supervisor) must be decided by someone else
    await page.getByRole('button', { name: 'Corrections' }).click()
    await page.getByRole('button', { name: 'Open' }).first().click()
    await expect(page.getByText('You requested this correction; someone else must decide it.')).toBeVisible()
    await page.keyboard.press('Escape')

    await signIn(page, 'ops')
    await page.goto('/attendance')
    await page.getByRole('tab', { name: 'Timesheets' }).click()
    await page.getByRole('button', { name: 'Corrections' }).click()
    await page.getByRole('button', { name: 'Open' }).first().click()
    await shot(page, 'flow-15-correction-review')
    await page.getByRole('button', { name: 'Approve correction' }).click()
    await expect(page.getByRole('dialog')).toBeHidden()

    await page.goto('/reports')
    await expect(page.getByText('Payable hours')).toBeVisible()
    await expect(page.getByText('Roster adherence')).toBeVisible()
    await expect(page.getByRole('table')).toContainText('Forecast error')
    await shot(page, 'flow-16-variance-report', true)
  })

  test('demand page shows readiness, forecast snapshot and work standards', async ({ page }) => {
    await signIn(page, 'planner')
    await page.goto('/demand')
    await expect(page.getByText('Data readiness')).toBeVisible()
    await expect(page.getByText('Work standards').first()).toBeVisible()
    await shot(page, 'flow-17-demand', true)
  })
})
