import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

const MOBILE_WIDTH = 375;
const MOBILE_HEIGHT = 667;

/**
 * モバイルビューポートでのUIレイアウトが正しく動作し、
 * 各要素がビューポート内に収まることを検証する。
 */
test.describe("Mobile layout", () => {
  test.beforeEach(async ({ page }) => {
    await page.setViewportSize({ width: MOBILE_WIDTH, height: MOBILE_HEIGHT });
  });

  test("composer emoji suggest fits within viewport", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/");
    await page.waitForSelector(".note-composer", { timeout: 10_000 });

    // テキストエリアに `:smi` を入力してインラインサジェストを表示
    const textarea = page.locator("form.note-composer textarea");
    await textarea.click();
    await textarea.type(":smi");

    // サジェストが表示されるのを待つ
    await page.waitForSelector(".emoji-suggest", { timeout: 5_000 });

    const box = await page.locator(".emoji-suggest").boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      // ビューポート内に収まっていること
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.y + box.height).toBeLessThanOrEqual(MOBILE_HEIGHT + 1);
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(MOBILE_WIDTH + 1);
    }
  });

  test("reaction emoji picker fits within viewport", async ({ page }) => {
    await loginAsAdmin(page);

    // ノートを作成
    const uid = Date.now();
    await createNote(page, `mobile-reaction-test-${uid}`);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // リアクション追加ボタンが表示されるのを待ち、クリック
    // モバイルビューポート + Firefox では Playwright の click() が空振りするため
    // evaluate で DOM クリックを直接発火させる + リトライ
    const addBtn = page.locator(".reaction-add-btn").first();
    await addBtn.waitFor({ state: "visible", timeout: 10_000 });
    await addBtn.scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
    await addBtn.evaluate((el) => (el as HTMLElement).click());

    const picker = page.locator(".emoji-picker");
    await expect(picker).toBeVisible({ timeout: 5_000 });

    const box = await picker.boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      expect(box.y).toBeGreaterThanOrEqual(0);
      expect(box.y + box.height).toBeLessThanOrEqual(MOBILE_HEIGHT + 1);
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(MOBILE_WIDTH + 1);
    }
  });

  test("navbar dropdown fits within viewport", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/");
    await page.waitForSelector(".navbar", { timeout: 10_000 });

    // ユーザーアバターをクリックしてドロップダウンを開く
    const avatar = page.locator(".navbar-avatar");
    await avatar.click();

    await page.waitForSelector(".navbar-dropdown", { timeout: 5_000 });

    const box = await page.locator(".navbar-dropdown").boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(MOBILE_WIDTH + 1);
    }
  });

  test("long display name does not overflow on profile", async ({ page }) => {
    await loginAsAdmin(page);

    // adminのプロフィールページに移動
    await page.goto("/@admin");
    await page.waitForSelector(".profile-display-name", { timeout: 10_000 });

    const nameEl = page.locator(".profile-display-name").first();
    const box = await nameEl.boundingBox();
    expect(box).not.toBeNull();
    if (box) {
      // 表示名がビューポート幅を超えないこと
      expect(box.x + box.width).toBeLessThanOrEqual(MOBILE_WIDTH + 1);
    }
  });
});
