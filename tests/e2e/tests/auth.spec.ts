import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("Authentication", () => {
  test("login page loads", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("#username")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("#password")).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test("login with valid credentials redirects to home", async ({ page }) => {
    await loginAsAdmin(page);
    await expect(page).toHaveURL("/");
  });

  test("login with wrong password shows error", async ({ page }) => {
    await page.goto("/login");
    await page.waitForSelector("#username", { timeout: 15_000 });
    await page.fill("#username", "admin");
    await page.fill("#password", "wrongpassword");
    await page.click('button[type="submit"]');

    // Should show an error message and stay on login page
    await expect(page.locator(".login-error, .error")).toBeVisible({ timeout: 5_000 });
  });

  test("authenticated API call works via nginx", async ({ page }) => {
    await loginAsAdmin(page);

    // verify_credentials should return 200 with the logged-in user
    const response = await page.request.get("/api/v1/accounts/verify_credentials");
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(body.username).toBe("admin");
  });

  test("unauthenticated API call returns 401", async ({ page }) => {
    const response = await page.request.get("/api/v1/accounts/verify_credentials");
    expect(response.status()).toBe(401);
  });
});
