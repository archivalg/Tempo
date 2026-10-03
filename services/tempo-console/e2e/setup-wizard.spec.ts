import { expect, test } from '@playwright/test'

// Platform-assisted onboarding of a brand-new organisation, then the customer administrator resuming guided setup (roadmap M6-ONBOARD, operational part).
const API = 'http://127.0.0.1:8017/v1'

test('a new organisation is walked through setup, remembers where it was, and a retry never makes a second site', async ({ page }) => {
  const id = `onb_${Date.now().toString(36)}`
  const email = `${id}@example.test`
  const op = await page.request.post(`${API}/auth/dev-login`, { data: { subject: 'idp|e2e-platform', email: 'platform@example.test', mfa: true } })
  const csrf = (await op.json()).csrf_token as string
  const made = await page.request.post(`${API}/platform/tenants`, { headers: { 'X-CSRF-Token': csrf }, data: { tenant_id: id, name: 'Onboarding Co', first_admin: { email }, initial_site_ids: ['onb_site_1'],
    subscription: { plan_key: 'optimise', licensed_sites: 1, worker_band: '250', manual_kind: 'pilot', reason: 'E2E onboarding pilot arrangement' } } })
  expect(made.status()).toBe(201)
  await page.request.post(`${API}/auth/logout`, { headers: { 'X-CSRF-Token': csrf } }).catch(() => undefined)

  const login = await page.request.post(`${API}/auth/dev-login`, { data: { subject: `idp|${id}`, email, mfa: true } })
  expect(login.ok()).toBeTruthy()
  await page.goto('/setup')
  await expect(page.getByRole('heading', { name: 'Guided setup' })).toBeVisible()
  await expect(page.getByLabel(/^Site ID/)).toHaveValue('onb_site_1')                         // the ID the platform reserved
  await page.getByLabel('Name', { exact: true }).fill('Onboarding DC')
  await page.getByLabel('Time zone').selectOption('Australia/Sydney')
  await page.getByRole('button', { name: 'Add site' }).click()
  await expect(page.getByText('Site added.')).toBeVisible()
  await expect(page.getByText('This step is complete')).toBeVisible()
  await page.getByRole('button', { name: 'Save changes' }).click()                            // a retry or double-click
  await expect(page.getByText('Site updated.')).toBeVisible()

  await page.getByRole('button', { name: /^3\. Your people/ }).click()
  await expect(page.getByText('What are you loading?')).toBeVisible()
  await page.getByRole('button', { name: /^7\. How people clock in/ }).click()
  await page.getByLabel('Decide later').click()
  await expect(page.getByLabel('Decide later')).toBeChecked()
  await expect(page.getByRole('navigation', { name: 'Setup steps' }).getByText('Done').first()).toBeVisible()

  await page.reload()                                                                          // resumes on the step it was left on
  await expect(page.getByRole('heading', { name: 'How people clock in' })).toBeVisible()
  await expect(page.getByLabel('Decide later')).toBeChecked()
  await page.getByRole('button', { name: /^6\. Labour rates/ }).click()
  await page.getByRole('button', { name: 'Skip for now' }).click()
  await expect(page.getByRole('navigation', { name: 'Setup steps' }).getByText('Skipped')).toBeVisible()
  await page.getByRole('button', { name: /^8\. Your first roster/ }).click()
  await expect(page.getByText('A few steps first')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Generate a draft for next week' })).toBeDisabled()    // honest: not ready until staff, standards and workload exist
})
