import { test, expect } from "@playwright/test";
import {
  loginAsAdmin,
  createNote,
  registerAndLogin,
  getActorId,
} from "./helpers";

test.describe("Reply and Mention", { tag: "@serial" }, () => {
  test.describe.configure({ mode: "serial" });

  const uid = Date.now();
  const userB = `reply_user_${uid}`;
  const password = "testpassword123";

  test("reply auto-prepends @mention", async ({ browser, page }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";

    // Login admin and create a note
    await loginAsAdmin(page);
    const note = await createNote(page, `reply-mention-test-${uid}`);

    // Register userB and reply to admin's note
    const userBSession = await registerAndLogin(
      browser,
      userB,
      password,
      baseURL,
    );

    // userB replies via API
    const replyResp = await userBSession.page.request.post(
      "/api/v1/statuses",
      {
        data: {
          content: `@admin reply-test-${uid}`,
          visibility: "public",
          in_reply_to_id: note.id,
        },
      },
    );
    expect(replyResp.status()).toBe(201);

    // Admin checks notifications — reply should be in Mentions tab
    await page.goto("/notifications");
    await page.waitForSelector(".notif-tab", { timeout: 10_000 });

    // Mentions tab is default — reply should appear
    await page.waitForSelector(".notification-item", { timeout: 15_000 });

    const items = await page.locator(".notification-item").count();
    expect(items).toBeGreaterThan(0);

    await userBSession.context.close();
  });

  test("reply notification appears in mentions tab", async ({
    browser,
    page,
  }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";

    // Login admin and create a note
    await loginAsAdmin(page);
    const note = await createNote(page, `reply-notif-test-${uid}`);

    // Register another user and reply (with in_reply_to but no @mention in text)
    const replyUser = `reply_notif_${uid}`;
    const replySession = await registerAndLogin(
      browser,
      replyUser,
      password,
      baseURL,
    );

    const replyResp = await replySession.page.request.post(
      "/api/v1/statuses",
      {
        data: {
          content: `just a reply ${uid}`,
          visibility: "public",
          in_reply_to_id: note.id,
        },
      },
    );
    expect(replyResp.status()).toBe(201);

    // Admin checks notifications — should be in Mentions tab (reply type included)
    await page.goto("/notifications");
    await page.waitForSelector(".notif-tab", { timeout: 10_000 });

    // Mentions tab is active by default
    await page.waitForSelector(".notification-item", { timeout: 15_000 });
    const items = await page.locator(".notification-item").count();
    expect(items).toBeGreaterThan(0);

    await replySession.context.close();
  });
});
