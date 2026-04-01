import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Reactions", () => {
  test("add reaction via emoji picker", async ({ page }) => {
    test.setTimeout(60_000);
    await loginAsAdmin(page);
    const uid = Date.now();
    await createNote(page, `reaction-test-${uid}`);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(`.note-card`)
      .filter({ hasText: `reaction-test-${uid}` })
      .first();

    // リアクション追加ボタンをクリック
    // Firefox では Playwright の click() が空振りするため evaluate で DOM 直接クリック
    const addBtn = noteCard.locator(".reaction-add-btn");
    await addBtn.waitFor({ state: "visible", timeout: 10_000 });
    await addBtn.scrollIntoViewIfNeeded();
    await addBtn.evaluate((el) => (el as HTMLElement).click());

    // Emoji Picker が表示される
    await page.waitForSelector(".emoji-picker", { timeout: 10_000 });

    // カスタム絵文字の非同期読み込みで DOM が再構築されるのを待つ
    await page.waitForFunction(
      () => {
        const btns = document.querySelectorAll(".emoji-picker .emoji-btn");
        return btns.length > 0;
      },
      { timeout: 10_000 },
    );

    // 最初の絵文字ボタンをクリック (evaluate で DOM detach を回避)
    await page.evaluate(() => {
      const btn = document.querySelector(".emoji-picker .emoji-btn") as HTMLElement;
      btn?.click();
    });

    // リアクションバッジが表示される
    await expect(noteCard.locator(".reaction-badge")).toBeVisible({
      timeout: 5_000,
    });
  });

  test("can reopen emoji picker after closing", async ({ page }) => {
    test.setTimeout(60_000);
    await loginAsAdmin(page);
    const uid = Date.now();
    await createNote(page, `reopen-picker-${uid}`);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(`.note-card`)
      .filter({ hasText: `reopen-picker-${uid}` })
      .first();

    const addBtn = noteCard.locator(".reaction-add-btn");
    await addBtn.waitFor({ state: "visible", timeout: 10_000 });
    await addBtn.scrollIntoViewIfNeeded();

    // 1回目: ピッカーを開く
    await addBtn.evaluate((el) => (el as HTMLElement).click());
    await page.waitForSelector(".emoji-picker", { timeout: 10_000 });

    // Escapeで閉じる
    await page.keyboard.press("Escape");
    await expect(page.locator(".emoji-picker")).not.toBeVisible({ timeout: 5_000 });

    // 2回目: 再度開けることを確認
    await addBtn.evaluate((el) => (el as HTMLElement).click());
    await expect(page.locator(".emoji-picker")).toBeVisible({ timeout: 10_000 });

    // 絵文字ボタンが表示されることも確認
    await page.waitForFunction(
      () => {
        const btns = document.querySelectorAll(".emoji-picker .emoji-btn");
        return btns.length > 0;
      },
      { timeout: 10_000 },
    );

    // backdropクリックで閉じる
    await page.locator(".reaction-emoji-backdrop").click({ force: true });
    await expect(page.locator(".emoji-picker")).not.toBeVisible({ timeout: 5_000 });

    // 3回目: もう一度開けることを確認
    await addBtn.evaluate((el) => (el as HTMLElement).click());
    await expect(page.locator(".emoji-picker")).toBeVisible({ timeout: 10_000 });
  });

  test("clicking own reaction removes it", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `unreact-test-${uid}`);

    // API でリアクション追加 (👍 を使用 — ⭐はお気に入りボタンに移動したため)
    await page.request.post(`/api/v1/statuses/${note.id}/react/%F0%9F%91%8D`);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(`.note-card`)
      .filter({ hasText: `unreact-test-${uid}` })
      .first();

    // 自分のリアクションバッジ (reaction-me) をクリックして解除
    const myBadge = noteCard.locator(".reaction-badge.reaction-me").first();
    await expect(myBadge).toBeVisible({ timeout: 5_000 });
    await myBadge.click();

    // reaction-me バッジが消える
    await expect(noteCard.locator(".reaction-badge.reaction-me")).toHaveCount(
      0,
      { timeout: 5_000 },
    );
  });
});
