import { test, expect } from "@playwright/test";
import { loginAsAdmin, registerAndLogin, getActorId } from "./helpers";

test.describe("Follow Requests", () => {
  const uid = Date.now();
  const password = "testpassword123";

  test("accept follow request", async ({ browser, page }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";

    const lockedUser = `locked_${uid}`;

    // ロックアカウントを作成
    const lockedSession = await registerAndLogin(
      browser,
      lockedUser,
      password,
      baseURL,
    );

    // locked (manually_approves_followers) を有効化
    const updateResp = await lockedSession.page.request.patch(
      "/api/v1/accounts/update_credentials",
      {
        multipart: { locked: "true" },
      },
    );
    expect(updateResp.ok()).toBeTruthy();

    // adminでログインしてロックユーザーのactor_idを取得してフォロー
    await loginAsAdmin(page);
    const lockedActorId = await getActorId(page, lockedUser);
    const followResp = await page.request.post(
      `/api/v1/accounts/${lockedActorId}/follow`,
    );
    expect(followResp.ok()).toBeTruthy();

    // ロックユーザーでフォローリクエストページを確認
    await lockedSession.page.goto("/follow-requests");
    await lockedSession.page.waitForSelector(".follow-request-item", {
      timeout: 10_000,
    });

    const items = await lockedSession.page
      .locator(".follow-request-item")
      .count();
    expect(items).toBeGreaterThan(0);

    // 承認ボタンをクリック
    const acceptBtn = lockedSession.page
      .locator(".follow-request-accept")
      .first();
    await acceptBtn.click();

    // リクエストがリストから消える
    await expect(
      lockedSession.page.locator(".follow-request-item"),
    ).toHaveCount(items - 1, { timeout: 5_000 });

    await lockedSession.context.close();
  });

  test("reject follow request", async ({ browser, page }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";

    const rejectUser = `locked_rej_${uid}`;
    const lockedSession = await registerAndLogin(
      browser,
      rejectUser,
      password,
      baseURL,
    );

    await lockedSession.page.request.patch(
      "/api/v1/accounts/update_credentials",
      {
        multipart: { locked: "true" },
      },
    );

    // adminからフォロー
    await loginAsAdmin(page);
    const lockedActorId = await getActorId(page, rejectUser);
    await page.request.post(`/api/v1/accounts/${lockedActorId}/follow`);

    // ロックユーザーでリクエスト確認
    await lockedSession.page.goto("/follow-requests");
    await lockedSession.page.waitForSelector(".follow-request-item", {
      timeout: 10_000,
    });

    // 拒否
    const rejectBtn = lockedSession.page
      .locator(".follow-request-reject")
      .first();
    await rejectBtn.click();

    await expect(
      lockedSession.page.locator(`.follow-request-item:has-text("admin")`),
    ).toHaveCount(0, { timeout: 5_000 });

    await lockedSession.context.close();
  });

  test("empty follow requests page shows message", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/follow-requests");

    await page.waitForSelector(".empty, .follow-request-item", {
      timeout: 10_000,
    });
    const empty = page.locator(".empty");
    if (await empty.isVisible()) {
      const text = await empty.textContent();
      expect(text).toBeTruthy();
    }
  });
});
