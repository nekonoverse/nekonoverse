import { execSync } from "child_process";
import { chromium } from "@playwright/test";

const BASE_URL = process.env.E2E_BASE_URL || "http://localhost:3080";

/**
 * Global setup: clear rate-limit keys and save admin session for reuse.
 * If the login fails, tests fall back to per-test UI login via loginAsAdmin().
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

  // Try to save admin storageState for reuse across tests
  try {
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
  } catch (e) {
    // Login failed — write empty storageState so Playwright doesn't error.
    // loginAsAdmin() in helpers.ts will handle per-test login as fallback.
    const fs = require("fs");
    const path = require("path");
    const authDir = path.join(__dirname, ".auth");
    fs.mkdirSync(authDir, { recursive: true });
    fs.writeFileSync(
      path.join(authDir, "admin.json"),
      JSON.stringify({ cookies: [], origins: [] }),
    );
    console.warn(`globalSetup: admin login failed, falling back to per-test login: ${e}`);
  }
}
