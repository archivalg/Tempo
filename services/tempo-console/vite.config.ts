/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/setupTests.ts'],
    // e2e/ holds Playwright specs (run via `npm run test:e2e`), not
    // Vitest ones — they use a different `test()` from @playwright/test
    // and vitest's default include pattern would otherwise pick them up.
    exclude: ['e2e/**', 'node_modules/**'],
  },
})
