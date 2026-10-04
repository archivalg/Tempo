import { expect, test, type Page } from '@playwright/test'

// The manager's side of the employee app, in a real browser, with a real employee session over the API (the same calls the phone makes).
const API = 'http://127.0.0.1:8017/v1'
const PERSONA: Record<string, RegExp> = { ops: /Demo Ops Manager/, planner: /Demo Planner/, admin: /Demo Tenant Admin/ }
async function signIn(p: Page, who: keyof typeof PERSONA) {
  await p.goto('/')
  const out = p.getByRole('button', { name: 'Sign out' })
  await p.locator('button:has-text("Sign out"), button:has-text("Demo ")').first().waitFor()
  if (await out.isVisible()) { await out.click(); await p.getByRole('button', { name: /Demo / }).first().waitFor() }
  for (let a = 0; a < 3 && !(await out.isVisible()); a++) { await p.getByRole('button', { name: PERSONA[who] }).click(); await out.waitFor({ timeout: 8000 }).catch(() => undefined) }
  await expect(out).toBeVisible()
}
const local = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

test('invite an employee, offer them a shift, they accept, the manager confirms; leave is requested and approved; access is removed', async ({ page, playwright }) => {
  await signIn(page, 'admin')
  await page.goto('/attendance?view=badges')
  const row = page.locator('tbody tr').filter({ hasText: 'Not invited' }).filter({ hasText: 'Active' }).first()
  const who = (await row.locator('td').first().innerText()).trim()
  await row.getByRole('button', { name: 'Invite' }).click()
  const link = await page.getByLabel('Link to open on their phone').inputValue()
  expect(link).toMatch(/^tempo:\/\/invite\?token=/)
  const token = link.split('token=')[1]
  await page.keyboard.press('Escape')
  await expect(page.locator('tbody tr').filter({ hasText: who })).toContainText('Invited')

  // the employee's phone, as the API sees it
  const phone = await playwright.request.newContext()
  const username = `e2e_${Date.now().toString(36)}`
  const pw = 'Correct-Horse-Battery-9!'
  const accepted = await phone.post(`${API}/auth/accept-invite`, { data: { token, username, password: pw } })
  expect(accepted.ok(), await accepted.text()).toBeTruthy()
  const login = await phone.post(`${API}/mobile/auth/login`, { data: { username, password: pw } })
  expect(login.ok()).toBeTruthy()
  const auth = { Authorization: `Bearer ${(await login.json()).access_token}` }
  expect((await (await phone.get(`${API}/me/profile`, { headers: auth })).json()).worker_id).toBeTruthy()
  await page.reload()
  await page.goto('/attendance?view=badges')
  await expect(page.locator('tbody tr').filter({ hasText: who })).toContainText('Joined')

  // the planner offers a shift (a month away, to stay clear of the seeded rosters)
  await signIn(page, 'planner')
  await page.goto('/offers')
  await page.getByRole('button', { name: 'New offer' }).click()
  const dlg = page.getByRole('dialog')
  const day = new Date(); day.setDate(day.getDate() + 30)
  await expect(dlg.getByText(who)).toBeVisible()
  await dlg.getByRole('checkbox', { name: new RegExp(who.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).check()
  await dlg.getByLabel('Role').fill('picker')
  await dlg.getByLabel('Zone').fill('pick_a')
  await dlg.getByLabel(/^Starts/).fill(`${local(day)}T06:00`)
  await dlg.getByLabel(/^Ends/).fill(`${local(day)}T14:00`)
  await dlg.getByLabel('Instructions').fill('Report to dock 3')
  await dlg.getByRole('button', { name: /^Send offer/ }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  await expect(page.getByRole('row').filter({ hasText: who }).filter({ hasText: 'No answer yet' }).first()).toBeVisible()

  // the employee sees and accepts it
  const offers = (await (await phone.get(`${API}/me/offers`, { headers: auth })).json()).offers.filter((o: { status_for_me: string }) => o.status_for_me === 'open')   // earlier runs may have left offers for the same demo worker
  expect(offers).toHaveLength(1)
  expect(offers[0].instructions).toBe('Report to dock 3')
  const acc = await phone.post(`${API}/me/offers/${offers[0].id}/respond`, { headers: auth, data: { action: 'accept' } })
  expect((await acc.json()).status).toBe('pending_confirmation')
  expect((await (await phone.get(`${API}/me/shifts`, { headers: auth })).json()).shifts.filter((s: { instructions: string }) => s.instructions === 'Report to dock 3')).toHaveLength(0)   // not on the roster yet

  await page.reload()
  await expect(page.getByText('Accepted — needs your confirmation')).toBeVisible()
  await page.getByRole('row').filter({ hasText: who }).filter({ hasText: 'Accepted' }).first().getByRole('button', { name: 'Manage' }).click()
  await page.getByRole('button', { name: 'Confirm onto the roster' }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  await page.getByRole('button', { name: 'All' }).click()
  await expect(page.getByText('Confirmed — on the roster').first()).toBeVisible()
  const mine = (await (await phone.get(`${API}/me/shifts`, { headers: auth })).json()).shifts.filter((s: { instructions: string }) => s.instructions === 'Report to dock 3')
  expect(mine.length).toBeGreaterThanOrEqual(1)

  // changing it after confirmation makes the employee reconfirm
  await page.getByRole('row').filter({ hasText: who }).filter({ hasText: 'Confirmed' }).first().getByRole('button', { name: 'Manage' }).click()
  await page.getByLabel('Instructions', { exact: true }).last().fill('Now report to dock 5')
  await page.getByRole('button', { name: 'Save change' }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  const changed = (await (await phone.get(`${API}/me/shifts`, { headers: auth })).json()).shifts.find((s: { instructions: string }) => s.instructions === 'Now report to dock 5')
  expect(changed.status).toBe('needs_reconfirmation')

  // leave
  const start = new Date(); start.setDate(start.getDate() + 60)
  const lr = await phone.post(`${API}/me/leave`, { headers: auth, data: { kind: 'annual', start_date: local(start), end_date: local(start), reason: 'e2e' } })
  expect(lr.status()).toBe(201)
  await signIn(page, 'ops')
  await page.goto('/requests')
  const lrow = page.getByRole('row').filter({ hasText: who }).first()
  await lrow.getByRole('button', { name: 'Decide' }).click()
  await page.getByLabel(/^Note to the employee/).fill('Enjoy')
  await page.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  const leave = (await (await phone.get(`${API}/me/leave`, { headers: auth })).json()).requests[0]
  expect(leave.status).toBe('approved')
  expect(leave.decision_note).toBe('Enjoy')

  // removing app access signs the phone out at once
  await signIn(page, 'admin')
  await page.goto('/attendance?view=badges')
  page.once('dialog', (d) => void d.accept())
  await page.locator('tbody tr').filter({ hasText: who }).getByRole('button', { name: 'Remove' }).first().click()
  await expect(page.locator('tbody tr').filter({ hasText: who })).toContainText('Not invited')
  expect([401, 403]).toContain((await phone.get(`${API}/me/shifts`, { headers: auth })).status())
  await phone.dispose()
})

test('an employee account cannot reach manager data', async ({ page, playwright }) => {
  await signIn(page, 'admin')
  await page.goto('/attendance?view=badges')
  const row = page.locator('tbody tr').filter({ hasText: 'Not invited' }).filter({ hasText: 'Active' }).first()
  const who = (await row.locator('td').first().innerText()).trim()
  await row.getByRole('button', { name: 'Invite' }).click()
  const token = (await page.getByLabel('Link to open on their phone').inputValue()).split('token=')[1]
  await page.keyboard.press('Escape')
  const phone = await playwright.request.newContext()
  const username = `e2e_${Date.now().toString(36)}b`
  const acc2 = await phone.post(`${API}/auth/accept-invite`, { data: { token, username, password: 'Correct-Horse-Battery-9!' } })
  expect(acc2.ok(), await acc2.text()).toBeTruthy()
  const login2 = await phone.post(`${API}/mobile/auth/login`, { data: { username, password: 'Correct-Horse-Battery-9!' } })
  expect(login2.ok()).toBeTruthy()
  const tok = (await login2.json()).access_token
  for (const path of ['/users', '/devices', '/sites/mel_dc_01/roster', '/sites/mel_dc_01/attendance/daily']) {
    expect([403, 404], path).toContain((await phone.get(`${API}${path}`, { headers: { Authorization: `Bearer ${tok}` } })).status())   // never a 200
  }
  await page.locator('tbody tr').filter({ hasText: who }).getByRole('button', { name: 'Remove' }).first().click().catch(() => undefined)
  await phone.dispose()
})

test('a team member signs in on the website and sees their own page (My shifts, offers, leave, clockings, notifications)', async ({ page, playwright }) => {
  await signIn(page, 'admin')
  await page.goto('/attendance?view=badges')
  const row = page.locator('tbody tr').filter({ hasText: 'Not invited' }).filter({ hasText: 'Active' }).first()
  const who = (await row.locator('td').first().innerText()).trim()
  await row.getByRole('button', { name: 'Invite' }).click()
  const token = (await page.getByLabel('Link to open on their phone').inputValue()).split('token=')[1]
  await page.keyboard.press('Escape')
  const api = await playwright.request.newContext()
  const username = `e2e_${Date.now().toString(36)}w`
  const pw = 'Correct-Horse-Battery-9!'
  expect((await api.post(`${API}/auth/accept-invite`, { data: { token, username, password: pw } })).ok()).toBeTruthy()
  await page.goto('/')
  await page.getByRole('button', { name: 'Sign out' }).click()
  const login = await page.request.post(`${API}/auth/login`, { data: { username, password: pw } })
  expect(login.ok()).toBeTruthy()
  await page.goto('/')
  await expect(page).toHaveURL(/\/my$/)                                                   // a team member is sent to their own page, not the manager screens
  await expect(page.getByRole('heading', { name: 'My shifts' })).toBeVisible()
  await expect(page.getByText('Tempo on the web for team members')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Roster Planner' })).toHaveCount(0)
  await page.getByRole('link', { name: 'Offers' }).click()
  await expect(page.getByRole('heading', { name: 'Shift offers' })).toBeVisible()
  await page.getByRole('link', { name: 'Leave & availability' }).click()
  await page.getByLabel('First day').fill('2027-03-01')
  await page.getByRole('button', { name: 'Send request' }).click()
  await expect(page.getByText('Waiting for your manager').first()).toBeVisible()
  await page.getByRole('link', { name: 'Clockings' }).click()
  await expect(page.getByRole('heading', { name: 'My clockings' })).toBeVisible()
  await page.getByRole('link', { name: 'Notifications' }).click()
  await expect(page.getByLabel('Send push notifications to my phone')).toBeChecked()
  await signIn(page, 'admin')
  await page.goto('/attendance?view=badges')
  page.once('dialog', (d) => void d.accept())
  await page.locator('tbody tr').filter({ hasText: who }).getByRole('button', { name: 'Remove' }).first().click()
  await api.dispose()
})
