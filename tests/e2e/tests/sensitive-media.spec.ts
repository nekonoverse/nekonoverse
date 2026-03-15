import { test, expect } from "@playwright/test";
import { loginAsAdmin } from "./helpers";

test.describe("Sensitive Media Overlay", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
  });

  test("sensitive note with media shows overlay instead of images", async ({
    page,
  }) => {
    // Create a sensitive note with media via API
    // First upload a test image
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

    // Create a sensitive note
    const noteResp = await page.request.post("/api/v1/statuses", {
      data: {
        content: `sensitive test ${Date.now()}`,
        visibility: "public",
        sensitive: true,
        media_ids: [media.id],
      },
    });
    expect(noteResp.status()).toBe(201);
    const note = await noteResp.json();

    // Navigate to the note
    await page.goto(`/notes/${note.id}`);
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // Overlay should be visible
    const overlay = page.locator(".sensitive-overlay");
    await expect(overlay).toBeVisible();

    // Image should NOT be visible
    const media_img = page.locator(".note-media-item img");
    await expect(media_img).toHaveCount(0);
  });

  test("clicking overlay reveals the image", async ({ page }) => {
    // Create sensitive note with media
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
        content: `sensitive reveal test ${Date.now()}`,
        visibility: "public",
        sensitive: true,
        media_ids: [media.id],
      },
    });
    const note = await noteResp.json();

    await page.goto(`/notes/${note.id}`);
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // Click overlay to reveal
    await page.click(".sensitive-overlay");

    // Image should now be visible
    const media_img = page.locator(".note-media-item img");
    await expect(media_img).toBeVisible();

    // Overlay should be gone
    await expect(page.locator(".sensitive-overlay")).toHaveCount(0);

    // Hide button should appear
    await expect(page.locator(".sensitive-hide-btn")).toBeVisible();
  });

  test("non-sensitive note shows images normally", async ({ page }) => {
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
        content: `normal test ${Date.now()}`,
        visibility: "public",
        sensitive: false,
        media_ids: [media.id],
      },
    });
    const note = await noteResp.json();

    await page.goto(`/notes/${note.id}`);
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // No overlay
    await expect(page.locator(".sensitive-overlay")).toHaveCount(0);

    // Image should be visible
    const media_img = page.locator(".note-media-item img");
    await expect(media_img).toBeVisible();
  });

  test("sensitive note with spoiler_text uses CW toggle instead of overlay", async ({
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
        content: `cw test ${Date.now()}`,
        visibility: "public",
        sensitive: true,
        spoiler_text: "NSFW warning",
        media_ids: [media.id],
      },
    });
    const note = await noteResp.json();

    await page.goto(`/notes/${note.id}`);
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    // CW toggle should be visible, not the sensitive overlay
    await expect(page.locator(".note-cw-toggle")).toBeVisible();
    await expect(page.locator(".sensitive-overlay")).toHaveCount(0);

    // Image should be hidden (behind CW)
    await expect(page.locator(".note-media-item img")).toHaveCount(0);
  });
});
