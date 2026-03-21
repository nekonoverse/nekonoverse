import { execSync } from "child_process";
import * as path from "path";

/**
 * Clear Valkey rate-limit counters before the E2E test suite runs,
 * so login and registration-heavy tests don't hit rate limits.
 */
export default async function globalSetup() {
  const projectRoot =
    process.env.PROJECT_ROOT ||
    process.env.GITHUB_WORKSPACE ||
    path.resolve(__dirname, "../..");

  const patterns = ["register_attempts:*", "login_attempts:*"];

  for (const pattern of patterns) {
    try {
      execSync(
        `docker compose -f docker-compose.e2e.yml exec -T valkey valkey-cli --scan --pattern "${pattern}" | while read key; do docker compose -f docker-compose.e2e.yml exec -T valkey valkey-cli DEL "$key"; done`,
        {
          cwd: projectRoot,
          stdio: "pipe",
          env: { ...process.env, COMPOSE_PROJECT_NAME: "neko-e2e" },
        },
      );
    } catch {
      // Valkey may not be reachable — silently skip
    }
  }
}
