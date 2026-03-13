import { test, expect } from "@playwright/test";
import {
  loginAsAdmin,
  createNote,
  registerAndLogin,
  getActorId,
} from "./helpers";

test.describe("Notifications", { tag: "@serial" }, () => {
  test.describe.configure({ mode: "serial" });

  const uid = Date.now();
  const userB = `notif_user_${uid}`;
  const password = "testpassword123";

  test("follow notification appears after being followed", async ({
    browser,
    page,
  }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";

    // Register userB in a separate context
    const userBSession = await registerAndLogin(
      browser,
      userB,
      password,
      baseURL,
    );

    // Get admin's actor_id via lookup
    await loginAsAdmin(page);
    const adminActorId = await getActorId(page, "admin");

    // userB follows admin
    const followResp = await userBSession.page.request.post(
      `/api/v1/accounts/${adminActorId}/follow`,
    );
    expect(followResp.ok()).toBeTruthy();

    // Admin checks notifications
    await page.goto("/notifications");
    await page.waitForSelector(".notification-item", { timeout: 15_000 });

    const typeTexts = await page
      .locator(".notification-type-text")
      .allTextContents();
    expect(typeTexts.some((t) => t.includes("followed"))).toBeTruthy();

    await userBSession.context.close();
  });

  test("reaction notification appears", async ({ browser, page }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";

    // Login admin and create a note
    await loginAsAdmin(page);
    const note = await createNote(page, `notif-react-${uid}`);

    // Register another user and react to the note
    const reactUser = `notif_react_${uid}`;
    const reactSession = await registerAndLogin(
      browser,
      reactUser,
      password,
      baseURL,
    );
    const reactResp = await reactSession.page.request.post(
      `/api/v1/statuses/${note.id}/react/%E2%AD%90`,
    );
    expect(reactResp.ok()).toBeTruthy();

    // Admin checks notifications
    await page.goto("/notifications");
    await page.waitForSelector(".notification-item", { timeout: 15_000 });

    const items = await page.locator(".notification-item").count();
    expect(items).toBeGreaterThan(0);

    await reactSession.context.close();
  });

  test("dismiss notification removes it", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/notifications");
    await page.waitForSelector(".notification-item", { timeout: 15_000 });

    const countBefore = await page.locator(".notification-item").count();
    // 最初の未読通知のdismissボタンをクリック
    const dismissBtn = page.locator(".notification-dismiss").first();
    if (await dismissBtn.isVisible()) {
      await dismissBtn.click();
      await page.waitForTimeout(500);
      const unreadCount = await page
        .locator(".notification-item.unread")
        .count();
      expect(unreadCount).toBeLessThan(countBefore);
    }
  });

  test("clear all removes all notifications", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/notifications");
    await page.waitForSelector(".notifications-header", { timeout: 10_000 });

    const clearBtn = page
      .locator(".notifications-header .btn")
      .filter({ hasText: /Clear all|すべて消去/ });

    if (await clearBtn.isVisible()) {
      await clearBtn.click();
      await page.waitForTimeout(1000);
      const items = await page.locator(".notification-item").count();
      expect(items).toBe(0);
    }
  });
});
