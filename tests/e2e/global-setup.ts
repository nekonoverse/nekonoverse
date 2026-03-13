import { execSync } from "child_process";

/**
 * Clear Valkey rate-limit counters before the E2E test suite runs,
 * so registration-heavy tests don't hit the 20-per-hour cap.
 */
export default async function globalSetup() {
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
}
