import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";

test.describe("Reactions", () => {
  test("add reaction via emoji picker", async ({ page }) => {
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
    await addBtn.click();

    // Emoji Picker が表示される
    await page.waitForSelector(".emoji-picker", { timeout: 5_000 });

    // 最初の絵文字ボタンをクリック
    const emoji = page.locator(".emoji-picker .emoji-btn").first();
    await emoji.waitFor({ timeout: 10_000 });
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

    // API でリアクション追加
    await page.request.post(`/api/v1/statuses/${note.id}/react/%E2%AD%90`);

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
