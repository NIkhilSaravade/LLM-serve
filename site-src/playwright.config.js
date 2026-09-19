import { defineConfig } from '@playwright/test'

// Opens the built single-file page straight from disk, so the test also proves it works offline.
export default defineConfig({
  testDir: './tests',
  timeout: 90_000,
  reporter: 'list',
  use: { browserName: 'chromium' },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true } },
  ],
})
