import { execSync } from "child_process";

/**
 * Clear Valkey rate-limit counters before the E2E test suite runs,
 * so registration-heavy tests don't hit the 20-per-hour cap.
 */
export default async function globalSetup() {
  const projectRoot =
    process.env.PROJECT_ROOT ||
    process.env.GITHUB_WORKSPACE ||
    "/home/server/app/nekonoverse";

  try {
    execSync(
      'docker compose -f docker-compose.e2e.yml exec -T valkey valkey-cli --scan --pattern "register_attempts:*" | while read key; do docker compose -f docker-compose.e2e.yml exec -T valkey valkey-cli DEL "$key"; done',
      {
        cwd: projectRoot,
        stdio: "pipe",
        env: { ...process.env, COMPOSE_PROJECT_NAME: "neko-e2e" },
      },
    );
  } catch {
    // Valkey may not be reachable in CI — silently skip
  }
}
