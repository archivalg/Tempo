import { expect, test } from '@playwright/test'

// Help library (roadmap M6-HELP): searchable, honest about what is not built, reachable from pages, with the API documentation linked.
test('help is searchable, labels what is planned, links from a page, and the API docs are the public subset', async ({ page, request }) => {
  await page.goto('/')
  await page.getByRole('button', { name: /Demo Supervisor/ }).click()
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
  await page.goto('/attendance')
  await page.getByRole('link', { name: 'Help with this page' }).click()
  await expect(page.getByRole('heading', { name: /daily list/ })).toBeVisible()          // contextual: the Today tab's article

  await page.goto('/help')
  await page.getByLabel('Search help').fill('payroll')
  await expect(page.getByRole('link', { name: /Corrections, approval, reopening and the payroll file/ })).toBeVisible()
  await page.getByLabel('Search help').fill('zzzz-nothing')
  await expect(page.getByText(/Nothing matches/)).toBeVisible()
  await page.getByLabel('Search help').fill('')
  await page.getByRole('link', { name: /Connecting Deputy or another workforce system/ }).click()
  await expect(page.getByText('Planned — not available')).toBeVisible()                  // never implies a live connection

  await page.goto('/help/api')
  await expect(page.getByRole('link', { name: 'Download the OpenAPI schema' })).toBeVisible()
  const spec = await request.get('http://127.0.0.1:8017/v1/api/openapi.json')
  const paths = Object.keys((await spec.json()).paths)
  expect(paths.every((p) => p.startsWith('/v1/imports/'))).toBeTruthy()
  expect((await request.get('http://127.0.0.1:8017/openapi.json')).status()).toBe(404)   // the framework's full schema is not published
})
