import { execSync } from "child_process";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL || "http://localhost:3080";

/**
 * Global setup: clear rate-limit keys and save admin session for reuse.
 */
export default async function globalSetup() {
  // Clear Valkey rate-limit counters
  try {
    execSync(
      'docker compose -f docker-compose.e2e.yml exec -T valkey valkey-cli --scan --pattern "register_attempts:*" | while read key; do docker compose -f docker-compose.e2e.yml exec -T valkey valkey-cli DEL "$key"; done',
      {
        cwd: process.env.PROJECT_ROOT || "/home/server/app/nekonoverse",
        stdio: "pipe",
      },
    );
  } catch {
    // Valkey may not be reachable in CI — silently skip
  }

  // Log in as admin once and save storageState for all tests
  const browser = await chromium.launch();
  const context = await browser.newContext({ baseURL: BASE_URL });
  const page = await context.newPage();

  await page.goto("/login");
  await page.waitForSelector("#username", { timeout: 15_000 });
  await page.fill("#username", "admin");
  await page.fill("#password", "testpassword123");

  const credentialsPromise = page.waitForResponse(
    (resp) =>
      resp.url().includes("/verify_credentials") && resp.status() === 200,
    { timeout: 15_000 },
  );
  await page.click('button[type="submit"]');
  await credentialsPromise;

  await context.storageState({ path: "tests/e2e/.auth/admin.json" });
  await browser.close();
}
