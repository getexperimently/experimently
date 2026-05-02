import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright configuration for the Experimently platform.
 *
 * Used by the scenario-runner agent for browser-based UI validation.
 * Can also be run directly for browser automation tests.
 *
 * Run:
 *   npx playwright test                    # all tests
 *   npx playwright test --headed           # with visible browser
 *   npx playwright test --ui               # interactive UI mode
 *   npx playwright show-report             # view HTML report
 *
 * Environment variables:
 *   PLAYWRIGHT_BASE_URL   — override default frontend URL (default: http://localhost:3100)
 *   PLAYWRIGHT_API_URL    — backend API URL (default: http://localhost:8000)
 *   PLAYWRIGHT_HEADLESS   — "false" to show browser window (default: "true")
 */

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3100";
const HEADLESS = process.env.PLAYWRIGHT_HEADLESS !== "false";

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,       // scenarios share state — run sequentially
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ["html", { outputFolder: "playwright-report", open: "never" }],
    ["list"],
  ],

  use: {
    baseURL: BASE_URL,
    headless: HEADLESS,
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    trace: "on-first-retry",

    // Generous timeouts for a dev environment
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // Start the Next.js dev server automatically if not already running
  webServer: process.env.PLAYWRIGHT_SKIP_SERVER
    ? undefined
    : {
        command: "npm run dev",
        url: BASE_URL,
        reuseExistingServer: true,
        timeout: 60_000,
      },

  // Output directories
  outputDir: "playwright-results",
});
