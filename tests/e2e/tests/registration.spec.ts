import { test, expect } from "@playwright/test";

test.describe("Registration", () => {
  test("register page loads", async ({ page }) => {
    await page.goto("/register");
    await expect(page.locator("#username")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("#email")).toBeVisible();
    await expect(page.locator("#password")).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test("can register a new user via API", async ({ page }) => {
    const username = `e2euser_${Date.now()}`;

    // Register via API
    const regResp = await page.request.post("/api/v1/accounts", {
      data: { username, email: `${username}@test.example.com`, password: "testpassword123" },
    });
    expect(regResp.status()).toBe(201);

    // Login via API
    const loginResp = await page.request.post("/api/v1/auth/login", {
      data: { username, password: "testpassword123" },
    });
    expect(loginResp.status()).toBe(200);

    // Verify credentials
    const credResp = await page.request.get("/api/v1/accounts/verify_credentials");
    expect(credResp.status()).toBe(200);
    const body = await credResp.json();
    expect(body.username).toBe(username);
  });

  test("shows error for duplicate username", async ({ page }) => {
    await page.goto("/register");
    await page.waitForSelector("#username", { timeout: 15_000 });

    await page.fill("#username", "admin");
    await page.fill("#email", "dup@test.example.com");
    await page.fill("#password", "testpassword123");
    await page.click('button[type="submit"]');

    // Should show an error
    await expect(page.locator(".login-error, .error")).toBeVisible({ timeout: 5_000 });
  });
});
