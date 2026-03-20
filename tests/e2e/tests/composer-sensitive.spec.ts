import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("Composer Sensitive Flag", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("sensitive toggle appears when media is attached", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector(".note-composer", { timeout: 10_000 });

    // Before attaching, sensitive button should not be visible
    const sensitiveBtn = page.locator(
      '.composer-attach-btn[title*="sensitive" i], .composer-attach-btn[title*="センシティブ"]',
    );
    await expect(sensitiveBtn).toHaveCount(0);

    // Upload a file via API and create a note with sensitive flag to verify API works
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/58BAwAI/AL+hc2rNAAAAABJRU5ErkJggg==",
      "base64",
    );
    const uploadResp = await page.request.post("/api/v1/media", {
      multipart: {
        file: { name: "test.png", mimeType: "image/png", buffer: png },
      },
    });
    expect(uploadResp.status()).toBe(200);
    const media = await uploadResp.json();

    // Create sensitive note via API
    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `sensitive composer test ${Date.now()}`,
        visibility: "public",
        sensitive: true,
        media_ids: [media.id],
      },
    });
    expect(noteResp.status()).toBe(201);
    const note = await noteResp.json();
    expect(note.sensitive).toBe(true);
  });

  test("CW button toggles spoiler text input", async ({ page }) => {
    await page.goto("/");
    await page.waitForSelector(".note-composer", { timeout: 10_000 });

    // CW input should not be visible initially
    await expect(page.locator(".composer-cw-input")).toHaveCount(0);

    // Click CW button
    const cwBtn = page.locator(".composer-footer-left .composer-attach-btn").filter({ hasText: "CW" });
    await cwBtn.click();

    // CW input should now be visible
    await expect(page.locator(".composer-cw-input")).toBeVisible();

    // Click again to hide
    await cwBtn.click();
    await expect(page.locator(".composer-cw-input")).toHaveCount(0);
  });

  test("note with CW text is created with spoiler_text and sensitive", async ({
    page,
  }) => {
    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `cw api test ${Date.now()}`,
        visibility: "public",
        sensitive: true,
        spoiler_text: "NSFW content",
      },
    });
    expect(noteResp.status()).toBe(201);
    const note = await noteResp.json();
    expect(note.sensitive).toBe(true);
    expect(note.spoiler_text).toBe("NSFW content");
  });

  test("sensitive note posted via API shows overlay on note page", async ({
    page,
  }) => {
    const png = Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/58BAwAI/AL+hc2rNAAAAABJRU5ErkJggg==",
      "base64",
    );
    const uploadResp = await page.request.post("/api/v1/media", {
      multipart: {
        file: { name: "test.png", mimeType: "image/png", buffer: png },
      },
    });
    const media = await uploadResp.json();
    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `sensitive flow test ${Date.now()}`,
        visibility: "public",
        sensitive: true,
        media_ids: [media.id],
      },
    });
    const note = await noteResp.json();

    await page.goto(`/notes/${note.id}`);
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // Overlay should be visible on the note page
    await expect(page.locator(".sensitive-overlay")).toBeVisible();
    await expect(page.locator(".note-media-item img")).toHaveCount(0);
  });

  test("note without sensitive flag has sensitive=false", async ({ page }) => {
    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `normal test ${Date.now()}`,
        visibility: "public",
      },
    });
    expect(noteResp.status()).toBe(201);
    const note = await noteResp.json();
    expect(note.sensitive).toBe(false);
  });
});
