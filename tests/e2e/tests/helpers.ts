import { type Page, type APIRequestContext, expect } from "@playwright/test";

/**
 * Log in as the pre-created admin user via the login form.
 * Navigates to /login, fills the form, submits, and waits for the
 * verify_credentials API call to confirm the session is established.
 */
export async function loginAsAdmin(page: Page) {
  await page.goto("/login");
  // Wait for SPA to render the form
  await page.waitForSelector("#username", { timeout: 15_000 });
  await page.fill("#username", "admin");
  await page.fill("#password", "testpassword123");

  // Listen for the verify_credentials response that confirms login
  const credentialsPromise = page.waitForResponse(
    (resp) => resp.url().includes("/verify_credentials") && resp.status() === 200,
    { timeout: 15_000 },
  );

  await page.click('button[type="submit"]');

  // Wait for both the redirect and the credentials check to complete
  await credentialsPromise;
  await page.waitForURL("/", { timeout: 10_000 });
}

/**
 * Navigate to admin page and click a specific tab.
 * Waits for the auth state to resolve and tabs to render.
 */
export async function goToAdminTab(page: Page, tabText: string) {
  await page.goto("/admin");
  // Wait for settings-tabs (appears only after auth state resolves)
  await page.waitForSelector(".settings-tabs", { timeout: 15_000 });
  await page.click(`.settings-tab:has-text("${tabText}")`);
}

/**
 * Generate a minimal 1x1 PNG as a Buffer for file upload tests.
 */
export function png1x1(): Buffer {
  return Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/58BAwAI/AL+hc2rNAAAAABJRU5ErkJggg==",
    "base64",
  );
}

/**
 * Create a note via the API. Requires an authenticated page (call loginAsAdmin first).
 * Returns the created note's JSON response.
 */
export async function createNote(page: Page, text: string) {
  const resp = await page.request.post("/api/v1/statuses", {
    data: { content: text, visibility: "public" },
  });
  expect(resp.status()).toBe(201);
  return resp.json();
}

/**
 * Register a new user via the API.
 * Returns the created user's JSON response.
 */
export async function registerUser(
  page: Page,
  username: string,
  password: string,
) {
  const resp = await page.request.post("/api/v1/auth/register", {
    data: {
      username,
      email: `${username}@test.example.com`,
      password,
    },
  });
  expect(resp.status()).toBe(201);
  return resp.json();
}
