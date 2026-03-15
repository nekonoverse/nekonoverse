import { test, expect } from "@playwright/test";
import { loginAsAdmin, goToAdminTab } from "./helpers";

test.describe("Admin System Accounts", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("system account appears in user list with system badge", async ({
    page,
  }) => {
    await goToAdminTab(page, "Users");

    // Wait for user list to load
    const userList = page.locator(".admin-user-list");
    await expect(userList).toBeVisible({ timeout: 10_000 });

    // instance.actor should be in the list
    const systemUser = userList.locator(
      ".admin-user-item:has-text('instance.actor')",
    );
    await expect(systemUser).toBeVisible();

    // System badge should be displayed
    const systemBadge = systemUser.locator(".admin-status-badge.system");
    await expect(systemBadge).toBeVisible();

    // Role badge (admin) should NOT be displayed for system accounts
    const roleBadge = systemUser.locator(".admin-role-badge");
    await expect(roleBadge).toHaveCount(0);
  });

  test("system account has no action buttons", async ({ page }) => {
    await goToAdminTab(page, "Users");

    const userList = page.locator(".admin-user-list");
    await expect(userList).toBeVisible({ timeout: 10_000 });

    const systemUser = userList.locator(
      ".admin-user-item:has-text('instance.actor')",
    );
    await expect(systemUser).toBeVisible();

    // No action buttons (suspend, silence, role select) should exist
    const actions = systemUser.locator(".admin-user-actions");
    await expect(actions).toHaveCount(0);
  });

  test("API rejects suspend on system account", async ({ page }) => {
    // Get user list to find system account ID
    const usersResp = await page.request.get("/api/v1/admin/users");
    expect(usersResp.status()).toBe(200);
    const users = await usersResp.json();
    const systemUser = users.find(
      (u: { username: string; is_system: boolean }) => u.is_system,
    );
    expect(systemUser).toBeDefined();

    const resp = await page.request.post(
      `/api/v1/admin/users/${systemUser.id}/suspend`,
      { data: {} },
    );
    expect(resp.status()).toBe(422);
    const body = await resp.json();
    expect(body.detail.toLowerCase()).toContain("system account");
  });

  test("API rejects role change on system account", async ({ page }) => {
    const usersResp = await page.request.get("/api/v1/admin/users");
    const users = await usersResp.json();
    const systemUser = users.find(
      (u: { username: string; is_system: boolean }) => u.is_system,
    );
    expect(systemUser).toBeDefined();

    const resp = await page.request.patch(
      `/api/v1/admin/users/${systemUser.id}/role`,
      { data: { role: "user" } },
    );
    expect(resp.status()).toBe(422);
    const body = await resp.json();
    expect(body.detail.toLowerCase()).toContain("system account");
  });

  test("system account cannot login via API", async ({ page }) => {
    const resp = await page.request.post("/api/v1/auth/login", {
      data: { username: "instance.actor", password: "anypassword" },
    });
    expect(resp.status()).toBe(401);
  });

  test("API rejects silence on system account", async ({ page }) => {
    const usersResp = await page.request.get("/api/v1/admin/users");
    const users = await usersResp.json();
    const systemUser = users.find(
      (u: { is_system: boolean }) => u.is_system,
    );
    expect(systemUser).toBeDefined();

    const resp = await page.request.post(
      `/api/v1/admin/users/${systemUser.id}/silence`,
      { data: {} },
    );
    expect(resp.status()).toBe(422);
    const body = await resp.json();
    expect(body.detail.toLowerCase()).toContain("system account");
  });

  test("user list API returns is_system field", async ({ page }) => {
    const resp = await page.request.get("/api/v1/admin/users");
    expect(resp.status()).toBe(200);
    const users = await resp.json();

    // All users should have is_system field
    for (const u of users) {
      expect(u).toHaveProperty("is_system");
      expect(typeof u.is_system).toBe("boolean");
    }

    // At least one system user (instance.actor)
    const systemUsers = users.filter(
      (u: { is_system: boolean }) => u.is_system,
    );
    expect(systemUsers.length).toBeGreaterThanOrEqual(1);
  });
});
