import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  retries: process.env.CI ? 0 : 1,
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.01 },
  },
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:3080",
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "firefox",
      use: { browserName: "firefox" },
    },
  ],
});
