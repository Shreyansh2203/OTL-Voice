import { defineConfig, devices } from '@playwright/test';

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './tests',
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 1 : 0,
  /* Run tests sequentially to avoid shared state / audio-context flakiness */
  workers: 1,
  /* Use a lightweight reporter in CI. */
  reporter: process.env.CI ? 'line' : 'html',
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: 'http://127.0.0.1:5173',

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      use: {
        contextOptions: { permissions: ['microphone'] }, ...devices['Desktop Chrome']
      },
    },
    {
      name: 'firefox',
      use: {
        ...devices['Desktop Firefox']
      },
      testIgnore: /visual\.spec\.ts/,
    },
    {
      name: 'webkit',
      use: {
        ...devices['Desktop Safari']
      },
      testIgnore: /visual\.spec\.ts/,
    },
  ],

  /* Use the caller-managed Vite server in CI to avoid nested process cleanup hangs. */
  webServer: process.env.PLAYWRIGHT_SKIP_WEBSERVER
    ? undefined
    : {
        command: 'pnpm exec vite --host 127.0.0.1',
        url: 'http://127.0.0.1:5173',
        reuseExistingServer: !process.env.CI,
        timeout: 120 * 1000,
      },
});

