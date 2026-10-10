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
  await page.locator('input[type=file]').setInputFiles({ name: filename, mimeType: 'text/csv', buffer: Buffer.from(csv) })
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
  await expect(page.getByText(/E2E-SO-1/)).toBeVisible()
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
  await expect(page.getByText(/E2E-SO-CONSTRAINED/)).toBeVisible()
  await expect(page.getByText(/feasible_with_slack/)).toBeVisible()  // not silently "feasible" — the shortfall is disclosed
  await page.screenshot({ path: '../../docs/screenshots/order-fulfillment-constrained-run.png', fullPage: true })
})

test('XLSX workbook upload and explicit order completion, through a real authenticated browser session', async ({ page }) => {
  // Neither capability has dedicated console UI yet (a known, stated gap — see
  // docs/order-driven-planning.md) — this proves both endpoints work end to end through the live
  // server with the browser's own cookie session and CSRF token, not just pytest's TestClient.
  await signIn(page, /Demo Tenant Admin/)
  await page.goto('/data')  // establishes the session on the API's own origin (credentials: 'include')

  const csrf = (await page.context().cookies(API_BASE)).find(c => c.name === 'tempo_csrf')?.value ?? ''
  const workbook = readFileSync(join(__dirname, 'fixtures', 'workers-v1.xlsx'))

  const staged = await page.request.post(`${API_BASE}/imports/xlsx/stage`, {
    headers: { 'Content-Type': 'application/octet-stream', 'X-CSRF-Token': csrf },
    data: workbook,
  })
  expect(staged.ok(), await staged.text()).toBeTruthy()
  const stagedBody = await staged.json()
  expect(stagedBody.skipped_sheets).toEqual([])
  const workersSheet = stagedBody.applied.find((s: { entity: string }) => s.entity === 'workers')
  expect(workersSheet.batch.ok_rows).toBe(1)  // only E2E-XLSX-1 (row 5) — E1042 on row 4 is the fixture's own guidance/example row, structurally ignored

  // Explicit order completion: create a tiny order via the existing CSV path, then confirm it done.
  await loadCsv(page, /Process templates/, 'process-templates-3.csv',
    'site,process_code,customer_id\nmel_dc_01,e2e_complete,\n', /^Load \d+ rows?$/)
  await loadCsv(page, /Process steps/, 'process-steps-3.csv',
    'site,process_code,sequence,activity\nmel_dc_01,e2e_complete,1,picking\n', /^Load \d+ rows?$/)
  const received = isoLocal(1, 1)
  const due = isoLocal(1, 10)
  await loadCsv(page, /^Orders/, 'orders-3.csv',
    `site,order_id,order_received,despatch_due,units,process_code\nmel_dc_01,E2E-COMPLETE-1,${received},${due},40,e2e_complete\n`, /^Load \d+ rows?$/)

  const complete = await page.request.post(`${API_BASE}/orders/E2E-COMPLETE-1/complete`, {
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    data: { quantity: 40 },
  })
  expect(complete.ok(), await complete.text()).toBeTruthy()
  const completeBody = await complete.json()
  expect(completeBody.status).toBe('completed')
  expect(completeBody.fulfilled_units).toBe(40)

  const order = await page.request.get(`${API_BASE}/orders/E2E-COMPLETE-1`, { headers: { 'X-CSRF-Token': csrf } })
  const orderBody = await order.json()
  expect(orderBody.outstanding_quantity).toBe(0)
  expect(orderBody.available_for_planning).toBe(0)
})
