import { defineConfig, devices } from '@playwright/test'

// A real end-to-end suite: a real browser (Chromium), against a real
// tempo-api instance (uvicorn) and a real console dev server (vite) —
// nothing here is mocked. `webServer` starts both, seeding the API's
// database from services/tempo-api/scripts/seed_e2e.py first so every
// run starts from an identical, known state.
//
// reuseExistingServer is deliberately always false (not the common
// !!process.env.CI pattern): this suite asserts against specific seeded
// values (a fixed worker count, a fixed PIN), so a stale server from a
// previous run — which `!!process.env.CI` would happily reuse locally —
// would make failures depend on what you happened to run last, not on
// what changed. Slower to start each time, deterministic every time.
const API_PORT = 8011
const CONSOLE_PORT = 5183

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // shared backend state — parallel specs would race each other's seeds
  // fullyParallel only serializes tests within one file — separate spec
  // files still run in their own workers by default, which raced against
  // this same shared backend (e.g. onboarding.spec.ts's freshly-registered
  // scope disappearing mid-assertion because another file's request hit
  // the server in between). One worker for the whole run, always.
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${CONSOLE_PORT}`,
    trace: 'retain-on-failure',
    launchOptions: {
      executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || '/opt/pw-browsers/chromium',
    },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `rm -f tempo_e2e.db && TEMPO_DATABASE_URL=sqlite:///./tempo_e2e.db python3 scripts/seed_e2e.py && TEMPO_DATABASE_URL=sqlite:///./tempo_e2e.db TEMPO_CONSOLE_CORS_ORIGINS=http://localhost:${CONSOLE_PORT} python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT}`,
      cwd: '../tempo-api',
      url: `http://localhost:${API_PORT}/healthz`,
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: `npm run dev -- --host 0.0.0.0 --port ${CONSOLE_PORT}`,
      env: { VITE_API_BASE_URL: `http://localhost:${API_PORT}/v1` },
      url: `http://localhost:${CONSOLE_PORT}`,
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
