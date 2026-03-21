import { execSync } from "child_process";
import { request } from "@playwright/test";
import * as fs from "fs";
import * as path from "path";

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

  // Log in as admin via API and save storageState for all tests
  const apiContext = await request.newContext({ baseURL: BASE_URL });
  const loginResp = await apiContext.post("/api/v1/auth/login", {
    data: { username: "admin", password: "testpassword123" },
  });

  if (!loginResp.ok()) {
    throw new Error(
      `globalSetup: admin login failed (${loginResp.status()}): ${await loginResp.text()}`,
    );
  }

  // Extract session cookie from login response
  const setCookieHeaders = loginResp.headersArray().filter(
    (h) => h.name.toLowerCase() === "set-cookie",
  );

  const cookies: Array<{
    name: string;
    value: string;
    domain: string;
    path: string;
    httpOnly: boolean;
    secure: boolean;
    sameSite: "Lax" | "Strict" | "None";
  }> = [];

  const urlObj = new URL(BASE_URL);
  for (const header of setCookieHeaders) {
    const parts = header.value.split(";").map((s) => s.trim());
    const [nameValue] = parts;
    const [name, ...valueParts] = nameValue.split("=");
    const value = valueParts.join("=");
    cookies.push({
      name,
      value,
      domain: urlObj.hostname,
      path: "/",
      httpOnly: true,
      secure: false,
      sameSite: "Lax",
    });
  }

  // Write storageState JSON
  const authDir = path.join(__dirname, ".auth");
  fs.mkdirSync(authDir, { recursive: true });
  const storageState = {
    cookies,
    origins: [],
  };
  fs.writeFileSync(
    path.join(authDir, "admin.json"),
    JSON.stringify(storageState, null, 2),
  );

  await apiContext.dispose();
}
