import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

// Playwright 1.59 otherwise adds an unmasked DOM snapshot to failure reports.
process.env.PLAYWRIGHT_NO_COPY_PROMPT = "1";

/** Real PostgreSQL/API/worker verification against an already staged server. */
export default defineConfig({
  testDir: "./tests/e2e-pharma",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: 1,
  timeout: 25_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  outputDir: path.resolve("../.deer-flow/pharma/e2e/results"),
  use: {
    baseURL: process.env.PHARMA_E2E_BASE_URL ?? "http://127.0.0.1:13027",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    // Authentication uses private deployment credentials. Never persist login
    // requests, cookie state, videos, or screenshots of an authentication error.
    trace: "off",
    video: "off",
    screenshot: "off",
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
    viewport: { width: 1440, height: 900 },
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
      },
    },
  ],
});
