import { test, expect } from "@playwright/test";
import { loginAsAdmin, goToAdminTab } from "./helpers";

test.describe("Admin Push Notification Settings", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("push settings section is visible on settings tab", async ({
    page,
  }) => {
    await goToAdminTab(page, "Server Settings");
    await expect(
      page.locator(".settings-section h3").first(),
    ).toBeVisible({ timeout: 10_000 });

    // Should have at least 4 settings sections (server settings, timeline, icon, push)
    const headings = page.locator(".settings-section h3");
    await expect(headings).toHaveCount(4, { timeout: 10_000 });
  });

  test("push enabled checkbox is present and checked by default", async ({
    page,
  }) => {
    await goToAdminTab(page, "Server Settings");
    await expect(
      page.locator(".settings-section h3").first(),
    ).toBeVisible({ timeout: 10_000 });

    // Find the push settings checkbox
    const pushCheckbox = page.locator(
      '.settings-section input[type="checkbox"]',
    );
    await expect(pushCheckbox).toBeVisible();
    await expect(pushCheckbox).toBeChecked();
  });

  test("toggle push enabled off and save persists", async ({ page }) => {
    await goToAdminTab(page, "Server Settings");
    await expect(
      page.locator(".settings-section h3").first(),
    ).toBeVisible({ timeout: 10_000 });

    // Uncheck push enabled
    const pushCheckbox = page.locator(
      '.settings-section input[type="checkbox"]',
    );
    await pushCheckbox.uncheck();
    await expect(pushCheckbox).not.toBeChecked();

    // Save
    await page.click('.settings-section button:has-text("Save")');
    await expect(page.locator(".settings-success")).toBeVisible({
      timeout: 5_000,
    });

    // Reload and verify persisted
    await goToAdminTab(page, "Server Settings");
    await expect(
      page.locator(".settings-section h3").first(),
    ).toBeVisible({ timeout: 10_000 });
    const checkboxAfter = page.locator(
      '.settings-section input[type="checkbox"]',
    );
    await expect(checkboxAfter).not.toBeChecked();

    // Re-enable for other tests
    await checkboxAfter.check();
    await page.click('.settings-section button:has-text("Save")');
    await expect(page.locator(".settings-success")).toBeVisible({
      timeout: 5_000,
    });
  });

  test("VAPID public key is displayed (derived from SECRET_KEY)", async ({
    page,
  }) => {
    await goToAdminTab(page, "Server Settings");
    await expect(
      page.locator(".settings-section h3").first(),
    ).toBeVisible({ timeout: 10_000 });

    // The VAPID public key input should contain a base64url string
    // (auto-derived from SECRET_KEY in e2e environment)
    const vapidInput = page.locator(
      '.settings-section input[readonly][style*="monospace"]',
    );
    await expect(vapidInput).toBeVisible({ timeout: 5_000 });
    const value = await vapidInput.inputValue();
    // base64url: alphanumeric + - + _ characters, at least 40 chars for a P-256 public key
    expect(value.length).toBeGreaterThan(40);
    expect(value).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  test("generate VAPID key button produces a new key", async ({ page }) => {
    await goToAdminTab(page, "Server Settings");
    await expect(
      page.locator(".settings-section h3").first(),
    ).toBeVisible({ timeout: 10_000 });

    // Get current key
    const vapidInput = page.locator(
      '.settings-section input[readonly][style*="monospace"]',
    );
    await expect(vapidInput).toBeVisible({ timeout: 5_000 });
    const oldKey = await vapidInput.inputValue();

    // Accept the confirm dialog
    page.on("dialog", (dialog) => dialog.accept());

    // Click generate button
    const generateBtn = page.locator(
      '.settings-section button:has-text("Generate"), .settings-section button:has-text("生成")',
    );
    await generateBtn.click();

    // Wait for key to update
    await expect(async () => {
      const val = await vapidInput.inputValue();
      expect(val).not.toBe(oldKey);
    }).toPass({ timeout: 5_000 });
    const newKey = await vapidInput.inputValue();

    // New key should be different from old and also be valid base64url
    expect(newKey.length).toBeGreaterThan(40);
    expect(newKey).toMatch(/^[A-Za-z0-9_-]+$/);
    expect(newKey).not.toBe(oldKey);
  });

  test("generated VAPID key persists after reload", async ({ page }) => {
    await goToAdminTab(page, "Server Settings");
    await expect(
      page.locator(".settings-section h3").first(),
    ).toBeVisible({ timeout: 10_000 });

    const vapidInput = page.locator(
      '.settings-section input[readonly][style*="monospace"]',
    );
    await expect(vapidInput).toBeVisible({ timeout: 5_000 });
    const currentKey = await vapidInput.inputValue();

    // Reload
    await goToAdminTab(page, "Server Settings");
    await expect(
      page.locator(".settings-section h3").first(),
    ).toBeVisible({ timeout: 10_000 });

    const vapidInputAfter = page.locator(
      '.settings-section input[readonly][style*="monospace"]',
    );
    await expect(vapidInputAfter).toBeVisible({ timeout: 5_000 });
    const keyAfterReload = await vapidInputAfter.inputValue();

    expect(keyAfterReload).toBe(currentKey);
  });

  // --- API-level tests ---

  test("generate-vapid-key API returns valid public key", async ({
    page,
  }) => {
    const resp = await page.request.post(
      "/api/v1/admin/push/generate-vapid-key",
    );
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body.vapid_public_key).toBeDefined();
    expect(body.vapid_public_key.length).toBeGreaterThan(40);
    expect(body.vapid_public_key).toMatch(/^[A-Za-z0-9_-]+$/);
  });

  test("generate-vapid-key API requires admin auth", async ({ page }) => {
    // Use a new context without auth
    const resp = await page.request.post(
      "/api/v1/admin/push/generate-vapid-key",
      {
        headers: { cookie: "" },
      },
    );
    // Should fail without valid session (401 or 403)
    expect(resp.status()).toBeGreaterThanOrEqual(400);
  });

  test("settings API returns push_enabled and vapid_public_key", async ({
    page,
  }) => {
    const resp = await page.request.get("/api/v1/admin/settings");
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(typeof body.push_enabled).toBe("boolean");
    expect(body.vapid_public_key).toBeDefined();
    // vapid_public_key is string or null
    if (body.vapid_public_key !== null) {
      expect(typeof body.vapid_public_key).toBe("string");
      expect(body.vapid_public_key.length).toBeGreaterThan(40);
    }
  });

  test("settings API can toggle push_enabled", async ({ page }) => {
    // Disable push
    const disableResp = await page.request.patch("/api/v1/admin/settings", {
      data: { push_enabled: false },
    });
    expect(disableResp.ok()).toBeTruthy();
    const disabled = await disableResp.json();
    expect(disabled.push_enabled).toBe(false);

    // Re-enable push
    const enableResp = await page.request.patch("/api/v1/admin/settings", {
      data: { push_enabled: true },
    });
    expect(enableResp.ok()).toBeTruthy();
    const enabled = await enableResp.json();
    expect(enabled.push_enabled).toBe(true);
  });

  test("instance API hides vapid_key when push is disabled", async ({
    page,
  }) => {
    // Disable push
    const disableResp = await page.request.patch("/api/v1/admin/settings", {
      data: { push_enabled: false },
    });
    expect(disableResp.ok()).toBeTruthy();

    // Check instance API
    const instanceResp = await page.request.get("/api/v1/instance");
    expect(instanceResp.ok()).toBeTruthy();
    const instance = await instanceResp.json();
    expect(instance.vapid_key).toBeUndefined();

    // Re-enable push
    await page.request.patch("/api/v1/admin/settings", {
      data: { push_enabled: true },
    });

    // Check instance API again
    const instanceResp2 = await page.request.get("/api/v1/instance");
    const instance2 = await instanceResp2.json();
    expect(instance2.vapid_key).toBeDefined();
    expect(typeof instance2.vapid_key).toBe("string");
  });
});
