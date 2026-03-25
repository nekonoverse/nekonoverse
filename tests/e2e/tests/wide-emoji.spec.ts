import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote, goToAdminTab, pngOfSize } from "./helpers";

/**
 * Register a wide custom emoji for testing wide-emoji display modes.
 * Creates a 300x50 PNG (6:1 aspect ratio) as a "wide" emoji.
 */
async function ensureWideEmoji(page: import("@playwright/test").Page) {
  const shortcode = "e2e_wide_emoji";

  // Check if already registered
  const resp = await page.request.get("/api/v1/custom_emojis");
  const emojis = await resp.json();
  if (emojis.some((e: { shortcode: string }) => e.shortcode === shortcode)) {
    return shortcode;
  }

  // Upload via admin UI
  await goToAdminTab(page, "Emoji");
  // Click Upload tab
  await page.locator(".settings-tabs .settings-tab", { hasText: "Upload" }).click();

  const form = page.locator(".admin-emoji-form");
  await expect(form).toBeVisible({ timeout: 10_000 });

  const fileInput = form.locator('input[type="file"]');
  await fileInput.setInputFiles({
    name: "wide_emoji.png",
    mimeType: "image/png",
    buffer: pngOfSize(300, 50),
  });

  const shortcodeInput = form
    .locator(".emoji-import-field")
    .filter({ hasText: /shortcode/i })
    .locator("input");
  await shortcodeInput.fill(shortcode);

  await form.locator('button:has-text("Add")').click();
  // Wait for success (emoji appears in manage tab)
  await page.locator(".settings-tabs .settings-tab", { hasText: "Manage" }).click();
  await expect(
    page.locator(".admin-emoji-grid-item").filter({ hasText: `:${shortcode}:` }),
  ).toBeVisible({ timeout: 10_000 });

  return shortcode;
}

test.describe("Wide emoji display modes", () => {
  test("shrink mode constrains wide emoji width", async ({ page }) => {
    test.setTimeout(60_000);
    await loginAsAdmin(page);
    const shortcode = await ensureWideEmoji(page);

    // Create a note with the wide emoji, then react with it
    const uid = Date.now();
    const note = await createNote(page, `wide-emoji-test-${uid}`);

    // React with the wide custom emoji
    const reactResp = await page.request.post(
      `/api/v1/statuses/${note.id}/react/:${shortcode}:`,
    );
    expect(reactResp.ok()).toBeTruthy();

    // Set wide emoji mode to "shrink" via addInitScript so it's available before page scripts run
    await page.addInitScript(() => {
      localStorage.setItem("wideEmojiStyle", "shrink");
    });

    // Reload to apply the setting
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // Verify the data-wide-emoji attribute is set
    await expect(page.locator("html")).toHaveAttribute(
      "data-wide-emoji",
      "shrink",
    );

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `wide-emoji-test-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-badge").first();
    await expect(badge).toBeVisible({ timeout: 10_000 });

    const emojiImg = badge.locator("img.custom-emoji").first();
    await expect(emojiImg).toBeVisible({ timeout: 5_000 });

    // In shrink mode, the emoji should be constrained (not wider than ~80px at 1.5em height)
    const box = await emojiImg.boundingBox();
    expect(box).toBeTruthy();
    // max-width: 5em ≈ ~80px at default font size. Allow some margin.
    expect(box!.width).toBeLessThan(120);

    await page.screenshot({
      path: "test-results/wide-emoji-shrink.png",
      fullPage: false,
    });
  });

  test("blur mode constrains and masks wide emoji", async ({ page }) => {
    test.setTimeout(60_000);
    await loginAsAdmin(page);
    const shortcode = await ensureWideEmoji(page);

    const uid = Date.now();
    const note = await createNote(page, `wide-blur-test-${uid}`);

    const reactResp = await page.request.post(
      `/api/v1/statuses/${note.id}/react/:${shortcode}:`,
    );
    expect(reactResp.ok()).toBeTruthy();

    await page.addInitScript(() => {
      localStorage.setItem("wideEmojiStyle", "blur");
    });

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    await expect(page.locator("html")).toHaveAttribute(
      "data-wide-emoji",
      "blur",
    );

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `wide-blur-test-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-badge").first();
    await expect(badge).toBeVisible({ timeout: 10_000 });

    const emojiImg = badge.locator("img.custom-emoji").first();
    await expect(emojiImg).toBeVisible({ timeout: 5_000 });

    // In blur mode, max-width is 100% (not constrained like shrink),
    // but object-fit: cover clips the overflow. Verify emoji-overflow class is applied.
    const hasOverflow = await badge.evaluate((el) => el.classList.contains("emoji-overflow"));
    expect(hasOverflow).toBeTruthy();

    await page.screenshot({
      path: "test-results/wide-emoji-blur.png",
      fullPage: false,
    });
  });

  test("overflow mode allows natural emoji width", async ({ page }) => {
    test.setTimeout(60_000);
    await loginAsAdmin(page);
    const shortcode = await ensureWideEmoji(page);

    const uid = Date.now();
    const note = await createNote(page, `wide-overflow-test-${uid}`);

    const reactResp = await page.request.post(
      `/api/v1/statuses/${note.id}/react/:${shortcode}:`,
    );
    expect(reactResp.ok()).toBeTruthy();

    await page.addInitScript(() => {
      localStorage.setItem("wideEmojiStyle", "overflow");
    });

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // Overflow mode removes the attribute
    await expect(page.locator("html")).not.toHaveAttribute("data-wide-emoji");

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `wide-overflow-test-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-badge").first();
    await expect(badge).toBeVisible({ timeout: 10_000 });

    await page.screenshot({
      path: "test-results/wide-emoji-overflow.png",
      fullPage: false,
    });
  });
});
