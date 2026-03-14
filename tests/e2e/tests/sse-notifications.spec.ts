import { test, expect } from "@playwright/test";
import {
  loginAsAdmin,
  createNote,
  registerAndLogin,
  getActorId,
} from "./helpers";

test.describe("SSE notification → notifications page", () => {
  test("reaction notification appears on page after SSE badge shows", async ({
    page,
    browser,
  }) => {
    // admin でログインしてノートを作成
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `sse-notif-${uid}`);

    // ホームに滞在し SSE 接続を確立
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // 別ユーザーがリアクション
    const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const { page: reactorPage, context: reactorCtx } =
      await registerAndLogin(browser, `ssereact${uid}`, "Pass1234!", baseURL);
    await reactorPage.request.post(
      `/api/v1/statuses/${note.id}/react/%E2%AD%90`,
    );
    await reactorCtx.close();

    // SSE でナビバーに未読バッジが表示されるのを待つ
    await expect(page.locator(".navbar-notif-badge")).toBeVisible({
      timeout: 10_000,
    });

    // 通知ページに遷移
    await page.goto("/notifications");
    await page.waitForSelector(".notif-tab", { timeout: 10_000 });

    // "Other" タブに切替（reaction は other に分類される）
    const otherTab = page.locator(".notif-tab").nth(1);
    await otherTab.click();

    // 通知アイテムが表示される（「通知はありません」ではない）
    await expect(page.locator(".notification-item").first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test("follow notification appears on page after SSE badge shows", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();

    // ホームに滞在し SSE 接続を確立
    await page.goto("/");
    await page.waitForSelector(".timeline", { timeout: 10_000 });

    // 別ユーザーが admin をフォロー
    const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const { page: followerPage, context: followerCtx } =
      await registerAndLogin(browser, `ssefollow${uid}`, "Pass1234!", baseURL);

    const adminActorId = await getActorId(followerPage, "admin");
    const followResp = await followerPage.request.post(
      `/api/v1/accounts/${adminActorId}/follow`,
    );
    expect(followResp.ok()).toBeTruthy();
    await followerCtx.close();

    // SSE でナビバーに未読バッジが表示されるのを待つ
    await expect(page.locator(".navbar-notif-badge")).toBeVisible({
      timeout: 10_000,
    });

    // 通知ページに遷移
    await page.goto("/notifications");
    await page.waitForSelector(".notif-tab", { timeout: 10_000 });

    // "Other" タブに切替（follow は other に分類される）
    const otherTab = page.locator(".notif-tab").nth(1);
    await otherTab.click();

    // フォロー通知が表示される
    const notifItems = page.locator(".notification-item");
    await expect(notifItems.first()).toBeVisible({ timeout: 10_000 });

    const typeTexts = await page
      .locator(".notification-type-text")
      .allTextContents();
    expect(typeTexts.some((t) => t.includes("followed"))).toBeTruthy();
  });

  test("mention notification appears in mentions tab after SSE", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();

    // ホームに滞在
    await page.goto("/");
    await page.waitForSelector(".timeline", { timeout: 10_000 });

    // 別ユーザーが admin をメンション
    const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const { page: mentionerPage, context: mentionerCtx } =
      await registerAndLogin(
        browser,
        `ssemention${uid}`,
        "Pass1234!",
        baseURL,
      );

    const mentionResp = await mentionerPage.request.post("/api/v1/statuses", {
      data: {
        content: `@admin SSE mention test ${uid}`,
        visibility: "public",
      },
    });
    expect(mentionResp.ok()).toBeTruthy();
    await mentionerCtx.close();

    // SSE バッジを待つ
    await expect(page.locator(".navbar-notif-badge")).toBeVisible({
      timeout: 10_000,
    });

    // 通知ページへ遷移（mentions タブがデフォルト）
    await page.goto("/notifications");
    await page.waitForSelector(".notif-tab", { timeout: 10_000 });

    // メンション通知が表示される
    await expect(page.locator(".notification-item").first()).toBeVisible({
      timeout: 10_000,
    });

    const noteContents = await page
      .locator(".notification-note")
      .allTextContents();
    expect(
      noteContents.some((c) => c.includes(`SSE mention test ${uid}`)),
    ).toBeTruthy();
  });

  test("notification page shows items when opened directly (no SSE wait)", async ({
    page,
    browser,
  }) => {
    // admin でログイン、ノート作成
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `direct-notif-${uid}`);

    // 別ユーザーがリアクション
    const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const { page: reactorPage, context: reactorCtx } =
      await registerAndLogin(browser, `directreact${uid}`, "Pass1234!", baseURL);
    await reactorPage.request.post(
      `/api/v1/statuses/${note.id}/react/%E2%AD%90`,
    );
    await reactorCtx.close();

    // SSE を待たずに少し間を置いて直接通知ページを開く
    await page.waitForTimeout(1000);
    await page.goto("/notifications");
    await page.waitForSelector(".notif-tab", { timeout: 10_000 });

    // "Other" タブに切替
    const otherTab = page.locator(".notif-tab").nth(1);
    await otherTab.click();

    // 通知が表示される
    await expect(page.locator(".notification-item").first()).toBeVisible({
      timeout: 10_000,
    });
  });
});
