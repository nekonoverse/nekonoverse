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

  // Log in as admin via page.request (browser context) and save storageState
  const browser = await chromium.launch();
  const context = await browser.newContext({ baseURL: BASE_URL });
  const page = await context.newPage();

  // Use page.request.post — same path as test helpers
  const loginResp = await page.request.post("/api/v1/auth/login", {
    data: { username: "admin", password: "testpassword123" },
  });

  if (!loginResp.ok()) {
    await browser.close();
    throw new Error(
      `globalSetup: admin login failed (${loginResp.status()}): ${await loginResp.text()}`,
    );
  }

  // Session cookie is automatically stored in context
  await context.storageState({ path: "tests/e2e/.auth/admin.json" });
  await browser.close();
}
