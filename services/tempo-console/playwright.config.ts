import { defineConfig, devices } from '@playwright/test'

// Runs against the LOCAL development stack (dev identity picker ON, loopback only): API 127.0.0.1:8017 + console 127.0.0.1:5174,
// both started by scripts/dev-up.sh against the seeded Ensemble demo (python -m app.cli bootstrap-ensemble-demo --reset).
// Nothing here is pointed at the public hostname. Chromium comes from the local Playwright cache.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 240_000,
  expect: { timeout: 15_000 },
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5174',
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined, args: ['--no-sandbox'] },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
})
