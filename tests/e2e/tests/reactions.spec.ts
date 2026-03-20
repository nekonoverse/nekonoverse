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
    const addBtn = noteCard.locator(".reaction-add-btn");
    await addBtn.waitFor({ state: "visible", timeout: 10_000 });
    await addBtn.scrollIntoViewIfNeeded();
    await addBtn.click();

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

    // 最初の絵文字ボタンをクリック (Firefox の再レンダリング安定を待つ)
    const emoji = page.locator(".emoji-picker .emoji-btn").first();
    await expect(emoji).toBeVisible({ timeout: 5_000 });
    await emoji.scrollIntoViewIfNeeded();
    await emoji.click();

    // リアクションバッジが表示される
    await expect(noteCard.locator(".reaction-badge")).toBeVisible({
      timeout: 5_000,
    });
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
