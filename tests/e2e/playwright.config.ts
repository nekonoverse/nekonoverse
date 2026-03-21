import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  globalSetup: "./global-setup.ts",
  testDir: "./tests",
  timeout: 30_000,
  workers: process.env.CI ? 2 : 4,
  retries: 1,
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.01 },
  },
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3080",
    screenshot: "only-on-failure",
    trace: "on-first-retry",
    storageState: ".auth/admin.json",
  },
  projects: [
    {
      name: "chromium",
      use: { browserName: "chromium" },
      testIgnore: /swipe/,
    },
    {
      name: "firefox",
      use: { browserName: "firefox" },
      testIgnore: /swipe/,
    },
    {
      name: "mobile-chromium",
      use: { ...devices["Pixel 7"] },
      testMatch: /swipe/,
    },
  ],
});
