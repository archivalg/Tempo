import { expect, test } from '@playwright/test'
import { KIOSK_PIN, KIOSK_WORKER_ID, setContext, SITE_ID, TENANT_ID } from './helpers'

const API_BASE_URL = 'http://localhost:8011/v1'

// The Onboarding page's "Clock-in credentials" form (see
// onboarding.spec.ts's own enrolment test) exercises enroll_credential
// through the UI already, so this test calls the API directly instead —
// a deliberate "API for setup, UI for the feature under test" split, the
// same one seeding itself uses, to keep this spec focused on the
// exception-detection behaviour rather than re-proving the form works.
async function enrollPin(request: import('@playwright/test').APIRequestContext, workerId: string, pin: string) {
  const response = await request.post(`${API_BASE_URL}/attendance/credentials`, {
    headers: {
      'X-Tempo-Context': JSON.stringify({
        tenant_id: TENANT_ID,
        site_ids: [SITE_ID],
        customer_ids: [],
        user_id: 'usr_e2e_admin',
        roles: ['tenant_admin'],
        purpose: 'labour.console',
        correlation_id: `cor_e2e_enroll_${Date.now()}`,
      }),
    },
    data: { worker_id: workerId, pin },
  })
  expect(response.ok()).toBeTruthy()
}

test('kiosk clock-in against a matching rostered shift, then clock-out', async ({ page }) => {
  await setContext(page)
  await page.goto('/kiosk')
  await expect(page.locator('h1')).toHaveText('Kiosk')

  await page.getByLabel('Site ID').fill(SITE_ID)
  await page.getByLabel('PIN').fill(KIOSK_PIN)
  await page.click('button:has-text("Identify")')

  await expect(page.locator('h2')).toContainText(KIOSK_WORKER_ID)
  await expect(page.locator('text=Not currently clocked in.')).toBeVisible()

  await page.click('button:has-text("Clock in")')
  await expect(page.locator('.hint').last()).toContainText('Clocked in at')
  // wrk_0 has a committed shift spanning now -/+ a few hours (seed_e2e.py) —
  // this must NOT report the "no matching rostered shift" fallback text.
  await expect(page.locator('.hint').last()).not.toContainText('no matching rostered shift')
  await expect(page.locator('text=Currently clocked in.')).toBeVisible()

  await page.click('button:has-text("Clock out")')
  await expect(page.locator('.hint').last()).toContainText('Clocked out. Shift duration:')
  await expect(page.locator('text=Not currently clocked in.')).toBeVisible()
})

test('an unrostered clock-in shows up as an exception in team attendance', async ({ page, request }) => {
  const strayWorkerId = 'wrk_1' // seeded by seed_named_roster_scenario, no ShiftAssignment
  const strayPin = '9876'
  await enrollPin(request, strayWorkerId, strayPin)

  await setContext(page)
  await page.goto('/kiosk')
  await page.getByLabel('Site ID').fill(SITE_ID)
  await page.getByLabel('PIN').fill(strayPin)
  await page.click('button:has-text("Identify")')
  await expect(page.locator('h2')).toContainText(strayWorkerId)

  await page.click('button:has-text("Clock in")')
  await expect(page.locator('.hint').last()).toContainText('no matching rostered shift')

  await page.goto('/attendance')
  await expect(page.locator('h1')).toHaveText('Team attendance')
  await page.getByLabel('Site ID').fill(SITE_ID)

  await expect(page.locator('h2:has-text("Exceptions")')).toBeVisible()
  await expect(page.locator('.exceptions')).toContainText(strayWorkerId)
  await expect(page.locator('table tbody')).toContainText(strayWorkerId)
})
