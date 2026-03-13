import { test, expect } from "@playwright/test";
import { loginAsAdmin, png1x1 } from "./helpers";

test.describe("Drive", () => {
  test("upload a file and see it listed", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/drive");
    await page.waitForSelector(".drive-header", { timeout: 10_000 });

    const uid = Date.now();
    const filename = `e2e-drive-${uid}.png`;

    // 隠しinputがDOMにアタッチされるのを待つ
    const fileInput = page.locator('input[type="file"]');
    await fileInput.waitFor({ state: "attached" });
    await fileInput.setInputFiles({
      name: filename,
      mimeType: "image/png",
      buffer: png1x1(),
    });

    // アップロード完了後にグリッドに表示される
    await expect(
      page.locator(`.drive-filename:has-text("e2e-drive-${uid}")`),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("delete a file from drive", async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto("/drive");
    await page.waitForSelector(".drive-header", { timeout: 10_000 });

    const uid = Date.now();
    const filename = `e2e-del-${uid}.png`;

    const fileInput = page.locator('input[type="file"]');
    await fileInput.waitFor({ state: "attached" });
    await fileInput.setInputFiles({
      name: filename,
      mimeType: "image/png",
      buffer: png1x1(),
    });

    // アップロード完了待ち
    const targetItem = page.locator(
      `.drive-filename:has-text("e2e-del-${uid}")`,
    );
    await expect(targetItem).toBeVisible({ timeout: 10_000 });

    // confirm ダイアログを自動承認
    page.on("dialog", (dialog) => dialog.accept());

    // アップロードしたファイルの削除ボタンをクリック
    const item = page.locator(
      `.drive-item:has(.drive-filename:has-text("e2e-del-${uid}"))`,
    );
    await item.locator(".drive-delete-btn").click();

    // 削除後: 対象ファイルがリストから消える
    await expect(targetItem).toHaveCount(0, { timeout: 5_000 });
  });
});
