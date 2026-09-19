import { defineConfig } from '@playwright/test'

// The page is served by scripts/serve.mjs with the real public/_headers applied, so the tests run
// against the same Content-Security-Policy and cache rules Cloudflare will use.
export default defineConfig({
  testDir: './tests',
  timeout: 120_000,
  reporter: 'list',
  workers: 2,
  use: { baseURL: 'http://localhost:4173', browserName: 'chromium' },
  webServer: {
    command: 'node scripts/serve.mjs',
    url: 'http://localhost:4173/robots.txt',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
  ],
})
