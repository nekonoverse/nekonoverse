import { test, expect } from "@playwright/test";
import { loginAsAdmin, registerAndLogin, getActorId } from "./helpers";

test.describe("Follow List", () => {
  const uid = Date.now();
  const userB = `follow_list_${uid}`;
  const password = "testpassword123";

  test("following tab shows followed user", async ({ browser, page }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";

    // userBを作成
    const userBSession = await registerAndLogin(
      browser,
      userB,
      password,
      baseURL,
    );

    // adminでログインしてuserBのactor_idを取得してフォロー
    await loginAsAdmin(page);
    const userBActorId = await getActorId(page, userB);
    const followResp = await page.request.post(
      `/api/v1/accounts/${userBActorId}/follow`,
    );
    expect(followResp.ok()).toBeTruthy();

    // adminのfollowingタブを確認
    await page.goto("/@admin/following");
    await page.waitForSelector(".follow-list-item", { timeout: 10_000 });

    const handles = await page.locator(".follow-list-handle").allTextContents();
    expect(handles.some((h) => h.includes(userB))).toBeTruthy();

    await userBSession.context.close();
  });

  test("followers tab shows follower", async ({ browser, page }) => {
    const baseURL = process.env.E2E_BASE_URL || "http://localhost:3080";

    const follower = `follower_${uid}`;
    const followerSession = await registerAndLogin(
      browser,
      follower,
      password,
      baseURL,
    );

    // adminのactor_idを取得
    const adminActorId = await getActorId(followerSession.page, "admin");

    // followerがadminをフォロー
    const followResp = await followerSession.page.request.post(
      `/api/v1/accounts/${adminActorId}/follow`,
    );
    expect(followResp.ok()).toBeTruthy();

    // adminのfollowersタブを確認
    await loginAsAdmin(page);
    await page.goto("/@admin/followers");
    await page.waitForSelector(".follow-list-item", { timeout: 10_000 });

    const handles = await page.locator(".follow-list-handle").allTextContents();
    expect(handles.some((h) => h.includes(follower))).toBeTruthy();

    await followerSession.context.close();
  });

  test("tab switching works between followers and following", async ({
    page,
  }) => {
    await loginAsAdmin(page);

    await page.goto("/@admin/followers");
    await page.waitForSelector(".follow-list-tabs", { timeout: 10_000 });

    // Followers タブがアクティブ
    const followersTab = page
      .locator(".follow-list-tab")
      .filter({ hasText: /Followers|フォロワー/ });
    await expect(followersTab).toHaveClass(/active/);

    // Following タブをクリック
    const followingTab = page
      .locator(".follow-list-tab")
      .filter({ hasText: /Following|フォロー中/ });
    await followingTab.click();
    await page.waitForURL(/@admin\/following/);
    await expect(followingTab).toHaveClass(/active/);
  });
});
