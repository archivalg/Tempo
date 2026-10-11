import { expect, test, type Page } from '@playwright/test'
import { readFileSync } from 'fs'
import { dirname, join } from 'path'
import { fileURLToPath } from 'url'

const API_BASE = process.env.E2E_API_BASE_URL ?? 'http://127.0.0.1:8111/v1'
const __dirname = dirname(fileURLToPath(import.meta.url))

// Order-driven-planning: upload process templates/steps/orders with a customer's own column names,
// create an order_fulfillment run, and see a structured result — upload through to results, in a
// real browser against the seeded Ensemble demo tenant (site mel_dc_01, activity "picking" already
// has a work standard, so no personal rate upload is needed for the demo's existing active workers).
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

async function loadCsv(page: Page, contractNameRegex: RegExp, filename: string, csv: string, loadButtonRegex: RegExp) {
  await page.getByRole('tab', { name: 'Load data' }).click()
  await page.getByRole('button', { name: contractNameRegex }).click()
  await page.getByLabel('CSV file').setInputFiles({ name: filename, mimeType: 'text/csv', buffer: Buffer.from(csv) })
  await page.getByRole('button', { name: 'Check the file' }).click()
  const result = page.getByRole('region', { name: 'Check result' })
  await expect(result).toBeVisible()
  const loadButton = result.getByRole('button', { name: loadButtonRegex })
  if (await loadButton.isVisible().catch(() => false)) {
    await loadButton.click()
  }
  await expect(result).toContainText('Loaded')
}

function isoLocal(daysFromNow: number, hour: number): string {
  const d = new Date()
  d.setUTCDate(d.getUTCDate() + daysFromNow)
  d.setUTCHours(hour, 0, 0, 0)
  return d.toISOString().slice(0, 19)
}

test('order-driven order_fulfillment run: upload, validate, create run, see results', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/data')
  await expect(page.getByRole('region', { name: 'Setup checklist' })).toBeVisible()

  await loadCsv(page, /Process templates/, 'process-templates.csv',
    'site,process_code,customer_id\nmel_dc_01,e2e_outbound,\n', /^Load \d+ rows?$/)
  await loadCsv(page, /Process steps/, 'process-steps.csv',
    'site,process_code,sequence,activity\nmel_dc_01,e2e_outbound,1,picking\n', /^Load \d+ rows?$/)

  const received = isoLocal(1, 1) // tomorrow, well inside both local-day boundaries regardless of timezone
  const due = isoLocal(1, 10)
  await loadCsv(page, /^Orders/, 'orders.csv',
    `site,order_id,order_received,despatch_due,units,process_code\nmel_dc_01,E2E-SO-1,${received},${due},50,e2e_outbound\n`, /^Load \d+ rows?$/)

  await page.screenshot({ path: '../../docs/screenshots/order-fulfillment-data-loaded.png', fullPage: true })

  await page.goto('/runs/new')
  await page.getByLabel('Run type').selectOption('order_fulfillment')
  await page.getByLabel(/Site IDs/).fill('mel_dc_01')
  await page.getByRole('button', { name: 'Create run' }).click()
  await page.waitForURL(/\/runs\/run_/, { timeout: 30_000 })
  await expect(page.getByText(/completed/i).first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('table', { name: 'Orders in this run' })).toContainText('E2E-SO-1')
  await page.screenshot({ path: '../../docs/screenshots/order-fulfillment-run-result.png', fullPage: true })
})

test('order-driven order_fulfillment run: a constrained order produces an explained shortfall, not a silent success', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/data')

  // Same process as the happy-path spec, but a despatch window far too short for the demo's
  // existing worker pool to clear the quantity — this must surface as feasible_with_slack with a
  // concrete explanation, never as a silent "completed" that hides the shortfall.
  await loadCsv(page, /Process templates/, 'process-templates-2.csv',
    'site,process_code,customer_id\nmel_dc_01,e2e_outbound_2,\n', /^Load \d+ rows?$/)
  await loadCsv(page, /Process steps/, 'process-steps-2.csv',
    'site,process_code,sequence,activity\nmel_dc_01,e2e_outbound_2,1,picking\n', /^Load \d+ rows?$/)
  const received = isoLocal(1, 1)
  const due = isoLocal(1, 2) // one hour — not enough to clear 50,000 units with the demo's picking rate
  await loadCsv(page, /^Orders/, 'orders-2.csv',
    `site,order_id,order_received,despatch_due,units,process_code\nmel_dc_01,E2E-SO-CONSTRAINED,${received},${due},50000,e2e_outbound_2\n`, /^Load \d+ rows?$/)

  await page.goto('/runs/new')
  await page.getByLabel('Run type').selectOption('order_fulfillment')
  await page.getByLabel(/Site IDs/).fill('mel_dc_01')
  await page.getByRole('button', { name: 'Create run' }).click()
  await page.waitForURL(/\/runs\/run_/, { timeout: 30_000 })
  await expect(page.getByText(/completed/i).first()).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('table', { name: 'Orders in this run' })).toContainText('E2E-SO-CONSTRAINED')
  await expect(page.getByText(/feasible_with_slack/)).toBeVisible()  // not silently "feasible" — the shortfall is disclosed
  await page.screenshot({ path: '../../docs/screenshots/order-fulfillment-constrained-run.png', fullPage: true })
})

test('XLSX workbook upload through the console UI', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/data?tab=upload')

  const workbook = readFileSync(join(__dirname, 'fixtures', 'workers-v1.xlsx'))
  await page.getByLabel('Workbook file').setInputFiles({ name: 'workers-v1.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: workbook })

  const sheetsTable = page.getByRole('table', { name: 'Sheets found' })
  await expect(sheetsTable).toBeVisible()
  await expect(sheetsTable).toContainText('workers')

  await page.getByRole('button', { name: /^Load \d+ sheets?$/ }).click()
  const resultSection = page.getByRole('region', { name: 'Workbook load result' })
  await expect(resultSection).toBeVisible()
  await expect(resultSection).toContainText('loaded')
  await expect(resultSection.getByRole('table', { name: 'Per-sheet result' })).toContainText('1 row loaded') // only E2E-XLSX-1 (row 5) — row 4 is the fixture's own guidance/example row, structurally ignored
  await page.screenshot({ path: '../../docs/screenshots/xlsx-upload-result.png', fullPage: true })
})

test('commit a draft plan, release the commitment, then confirm order completion — all through the console UI', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/data')

  await loadCsv(page, /Process templates/, 'process-templates-3.csv',
    'site,process_code,customer_id\nmel_dc_01,e2e_complete,\n', /^Load \d+ rows?$/)
  await loadCsv(page, /Process steps/, 'process-steps-3.csv',
    'site,process_code,sequence,activity\nmel_dc_01,e2e_complete,1,picking\n', /^Load \d+ rows?$/)
  const received = isoLocal(1, 1)
  const due = isoLocal(1, 10)
  await loadCsv(page, /^Orders/, 'orders-3.csv',
    `site,order_id,order_received,despatch_due,units,process_code\nmel_dc_01,E2E-COMPLETE-1,${received},${due},40,e2e_complete\n`, /^Load \d+ rows?$/)

  // Draft run first: a draft must not reserve anything, and offers a "Commit this plan" action.
  await page.goto('/runs/new')
  await page.getByLabel('Run type').selectOption('order_fulfillment')
  await page.getByLabel(/Site IDs/).fill('mel_dc_01')
  await expect(page.getByText('Commit this plan')).toBeVisible()
  await page.getByRole('button', { name: 'Create run' }).click()
  await page.waitForURL(/\/runs\/run_/, { timeout: 30_000 })
  await expect(page.getByText(/completed/i).first()).toBeVisible({ timeout: 30_000 })
  const orderPanel = page.getByRole('group', { name: 'Order E2E-COMPLETE-1' })
  await expect(orderPanel).toBeVisible()

  const commitmentSection = page.getByRole('region', { name: 'Commitment' })
  await expect(commitmentSection).toContainText('draft')
  const commitButton = commitmentSection.getByRole('button', { name: 'Commit this plan' })
  await expect(commitButton).toBeVisible()
  await commitButton.click()
  await page.waitForURL(/\/runs\/run_/, { timeout: 30_000 }) // navigates to the new committed run
  await expect(page.getByText(/completed/i).first()).toBeVisible({ timeout: 30_000 })
  const committedSection = page.getByRole('region', { name: 'Commitment' })
  await expect(committedSection).toContainText('committed')
  await expect(committedSection.getByRole('button', { name: 'Release this commitment' })).toBeVisible()
  const orderPanel2 = page.getByRole('group', { name: 'Order E2E-COMPLETE-1' })

  // Confirm partial completion through the per-order lifecycle panel, before releasing.
  await orderPanel2.getByLabel('Confirm units completed').fill('15')
  await orderPanel2.getByRole('button', { name: 'Confirm completion' }).click()
  await expect(orderPanel2.getByText(/Confirmed 15 units completed/)).toBeVisible()
  await expect(orderPanel2.getByText('Actually completed so far:').locator('..')).toContainText('15')
  await expect(orderPanel2.getByText('Outstanding (not yet completed):').locator('..')).toContainText('25')
  await page.screenshot({ path: '../../docs/screenshots/order-partial-completion.png', fullPage: true })

  // Release the commitment: capacity becomes available again, without touching what was completed.
  // This commit claimed every open order at the site within the default window (not only
  // E2E-COMPLETE-1 — this run also shares the site with other orders this spec file has already
  // created), so the release count reflects however many that was, not just this one order.
  await committedSection.getByRole('button', { name: 'Release this commitment' }).click()
  await expect(page.getByText(/Released \d+ order allocations?/)).toBeVisible()
  await expect(committedSection).toContainText('released')
  await expect(committedSection.getByRole('button', { name: 'Release this commitment' })).toHaveCount(0) // cannot be released twice from the UI
  await expect(orderPanel2.getByText('Actually completed so far:').locator('..')).toContainText('15') // completion untouched by release

  // Finish the order off completely.
  await orderPanel2.getByLabel('Confirm units completed').fill('25')
  await orderPanel2.getByRole('button', { name: 'Confirm completion' }).click()
  await expect(orderPanel2.getByText(/Confirmed 25 units completed/)).toBeVisible()
  await expect(orderPanel2.getByText('Outstanding (not yet completed):').locator('..')).toContainText('0')
  await expect(orderPanel2.getByText('Available for planning:').locator('..')).toContainText('0')
  await page.screenshot({ path: '../../docs/screenshots/order-full-completion.png', fullPage: true })
})

test('a repeated completion confirmation past the order quantity is reported truthfully, never double-counted', async ({ page }) => {
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/data')
  await loadCsv(page, /Process templates/, 'process-templates-4.csv',
    'site,process_code,customer_id\nmel_dc_01,e2e_dup,\n', /^Load \d+ rows?$/)
  await loadCsv(page, /Process steps/, 'process-steps-4.csv',
    'site,process_code,sequence,activity\nmel_dc_01,e2e_dup,1,picking\n', /^Load \d+ rows?$/)
  const received = isoLocal(1, 1)
  const due = isoLocal(1, 10)
  await loadCsv(page, /^Orders/, 'orders-4.csv',
    `site,order_id,order_received,despatch_due,units,process_code\nmel_dc_01,E2E-DUP-1,${received},${due},10,e2e_dup\n`, /^Load \d+ rows?$/)

  await page.goto('/runs/new')
  await page.getByLabel('Run type').selectOption('order_fulfillment')
  await page.getByLabel(/Site IDs/).fill('mel_dc_01')
  await page.getByRole('button', { name: 'Create run' }).click()
  await page.waitForURL(/\/runs\/run_/, { timeout: 30_000 })
  const orderPanel = page.getByRole('group', { name: 'Order E2E-DUP-1' })
  await expect(orderPanel).toBeVisible({ timeout: 30_000 })

  await orderPanel.getByLabel('Confirm units completed').fill('10')
  await orderPanel.getByRole('button', { name: 'Confirm completion' }).click()
  await expect(orderPanel.getByText(/Confirmed 10 units completed/)).toBeVisible()

  // A second confirmation once the order is already fully completed records nothing new — the
  // server clamps to the order's own quantity (app/api/v1/orders.py::complete_order) rather than
  // double-counting, and the UI must say plainly that nothing further was confirmed, not repeat the
  // original success message as if another 10 units had just been completed.
  await orderPanel.getByLabel('Confirm units completed').fill('10')
  await orderPanel.getByRole('button', { name: 'Confirm completion' }).click()
  await expect(orderPanel.getByText(/Confirmed 0 units completed/)).toBeVisible()
  await expect(orderPanel.getByText('Outstanding (not yet completed):').locator('..')).toContainText('0')
})
