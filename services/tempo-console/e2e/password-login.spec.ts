import { expect, test, type Page } from '@playwright/test'
import { createHmac } from 'node:crypto'

// Real username/password sign-in in a browser: invitation → choose password → sign in → admin authenticator setup → TOTP sign-in.
const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8017/v1'
const SHOTS = '../../docs/screenshots'
const shot = (p: Page, name: string) => p.screenshot({ path: `${SHOTS}/${name}.png` })

function totp(secret: string, at = Date.now()): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'
  let bits = ''
  for (const c of secret.replace(/=+$/, '')) bits += alphabet.indexOf(c).toString(2).padStart(5, '0')
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)))
  const buf = Buffer.alloc(8); buf.writeBigUInt64BE(BigInt(Math.floor(at / 30000)))
  const h = createHmac('sha1', key).update(buf).digest(); const o = h[h.length - 1] & 15
  return String(((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000)).padStart(6, '0')
}
const PW = 'e2e passphrase 8841 zebra'
const RUN = Date.now().toString(36)
const PLANNER = `planner-${RUN}`, ADMIN = `admin-${RUN}`

test.describe.serial('password sign-in', () => {
  const email = `e2e.${Date.now()}@example.test`
  let inviteUrl = ''

  test('an administrator invites a person; the one-time link sets their password', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Demo Tenant Admin/ }).click()
    await page.goto('/admin')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Planner').check()
    await page.getByRole('button', { name: 'Invite', exact: true }).click()
    const link = page.locator('code').filter({ hasText: '/invite?token=' })
    await expect(link).toBeVisible()
    inviteUrl = (await link.innerText()).trim()
    await shot(page, 'login-01-invite-link')
    await page.getByRole('button', { name: 'Sign out' }).click()

    await page.goto(inviteUrl.replace(/^https?:\/\/[^/]+/, ''))
    await expect(page.getByText(email)).toBeVisible()
    await page.getByLabel('Username').fill(PLANNER)
    await page.getByLabel(/^New password/).fill('short')
    await page.getByLabel('Repeat password').fill('short')
    await expect(page.getByRole('button', { name: 'Set password' })).toBeDisabled()
    await page.getByLabel(/^New password/).fill(PW); await page.getByLabel('Repeat password').fill(PW)
    await shot(page, 'login-02-set-password')
    await page.getByRole('button', { name: 'Set password' }).click()
    await expect(page.getByText('Sign in').first()).toBeVisible()
    // the link is single-use
    await page.goto(inviteUrl.replace(/^https?:\/\/[^/]+/, ''))
    await expect(page.getByText(/invalid or has expired/)).toBeVisible()
  })

  test('sign in with the password; wrong password gives one generic message; then lockout', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('Username or email').fill(PLANNER); await page.getByLabel('Password').fill('not the right one 1')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: /sign you in/ })).toContainText('Incorrect username or password')
    await shot(page, 'login-03-wrong-password')
    await page.getByLabel('Username or email').fill(PLANNER); await page.getByLabel('Password').fill(PW)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('link', { name: 'Roster Planner', exact: true })).toBeVisible()
    await expect(page.getByText('Local development identity')).toBeVisible()  // dev banner only because this is the local stack
    await shot(page, 'login-04-signed-in')
    // change password from the account page
    await page.goto('/account')
    await page.getByLabel('Current password').fill(PW)
    await page.getByLabel('New password (12+ characters)').fill(PW + '!'); await page.getByLabel('Repeat new password').fill(PW + '!')
    await page.getByRole('button', { name: 'Change password' }).click()
    await expect(page.getByText('Password changed.')).toBeVisible()
    await shot(page, 'login-05-account')
    await page.getByRole('button', { name: 'Sign out' }).click()
    for (let i = 0; i < 5; i++) {
      await page.getByLabel('Username or email').fill(PLANNER); await page.getByLabel('Password').fill(`wrong-wrong-${i}-wrong`)
      await page.getByRole('button', { name: 'Sign in', exact: true }).click()
      await expect(page.getByRole('alert').filter({ hasText: /sign you in/ })).toContainText('Incorrect username or password')
    }
    await page.getByLabel('Username or email').fill(PLANNER); await page.getByLabel('Password').fill(PW + '!')
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: /sign you in/ })).toContainText('temporarily locked')  // correct password refused while locked
  })

  test('an administrator must set up an authenticator; later sign-ins ask for the code', async ({ page, request }) => {
    // create an admin invitation through the API as the demo tenant admin (dev identity, local only)
    const ctx = await request.post(`${API}/auth/dev-login`, { data: { subject: 'dev|tenant_admin', email: 'tenant_admin@demo.tempo.invalid', mfa: true } })
    const csrf = (await ctx.headersArray()).filter((h) => h.name.toLowerCase() === 'set-cookie').map((h) => h.value).join(';').match(/tempo_csrf=([^;]+)/)![1]
    const adminEmail = `admin.${Date.now()}@example.test`
    const inv = await request.post(`${API}/admin/users`, { headers: { 'X-CSRF-Token': csrf }, data: { email: adminEmail, roles: ['tenant_admin'], site_ids: ['mel_dc_01'], customer_ids: [] } })
    expect(inv.ok()).toBeTruthy()
    const token = (await inv.json()).invite_token as string
    await page.goto(`/invite?token=${token}`)
    await page.getByLabel('Username').fill(ADMIN)
    await page.getByLabel(/^New password/).fill(PW); await page.getByLabel('Repeat password').fill(PW)
    await page.getByRole('button', { name: 'Set password' }).click()
    await page.getByLabel('Username or email').fill(ADMIN); await page.getByLabel('Password').fill(PW)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByText('Set up two-step verification')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Administration', exact: true })).toHaveCount(0)  // no admin authority yet
    await shot(page, 'login-06-mfa-required')
    await page.goto('/account')
    await page.getByRole('button', { name: 'Set up authenticator' }).click()
    await expect(page.getByRole('img', { name: /QR code to add Tempo/ })).toBeVisible()
    const secret = (await page.getByLabel('Setup key').innerText()).replace(/\s+/g, '')
    await shot(page, 'login-07-mfa-setup')
    await page.getByLabel(/Enter the 6-digit code/).fill(totp(secret))
    await page.getByRole('button', { name: 'Confirm and turn on' }).click()
    await expect(page.getByText('Two-step verification is on.')).toBeVisible()
    await expect(page.getByRole('link', { name: 'Administration', exact: true })).toBeVisible()  // admin authority appears once MFA-verified
    await page.getByRole('button', { name: 'Sign out' }).click()
    await page.getByLabel('Username or email').fill(ADMIN); await page.getByLabel('Password').fill(PW)
    await page.getByRole('button', { name: 'Sign in', exact: true }).click()
    await expect(page.getByLabel('Authentication code')).toBeVisible()
    await shot(page, 'login-08-mfa-prompt')
    await page.getByLabel('Authentication code').fill('000000')
    await page.getByRole('button', { name: 'Verify' }).click()
    await expect(page.getByRole('alert').filter({ hasText: /sign you in/ })).toContainText('not valid')
    // a fresh code from the next 30 s step (the previous one was consumed at enrolment)
    await page.getByLabel('Authentication code').fill(totp(secret, Date.now() + 30000))
    await page.getByRole('button', { name: 'Verify' }).click()
    await expect(page.getByRole('link', { name: 'Administration', exact: true })).toBeVisible()
  })
})
