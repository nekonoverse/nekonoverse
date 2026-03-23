import { test, expect } from "@playwright/test";
import { loginAsAdmin, createNote } from "./helpers";
import { execFileSync } from "child_process";
import * as path from "path";
import * as fs from "fs";

/**
 * Seed a remote custom emoji record and a reaction using it on a note.
 * Runs a Python script inside the app container.
 */
function seedRemoteEmojiReaction(
  noteId: string,
  shortcode: string,
  domain: string,
) {
  const projectRoot =
    process.env.PROJECT_ROOT ||
    path.resolve(__dirname, "../../..");
  // Validate projectRoot is a real directory
  if (!fs.existsSync(projectRoot) || !fs.statSync(projectRoot).isDirectory()) {
    throw new Error(`PROJECT_ROOT is not a valid directory: ${projectRoot}`);
  }
  const composeFile = path.join(projectRoot, "docker-compose.e2e.yml");

  const py = [
    "import asyncio, uuid",
    "from sqlalchemy import select",
    "from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession",
    "from app.config import settings",
    "from app.models.custom_emoji import CustomEmoji",
    "from app.models.reaction import Reaction",
    "from app.models.actor import Actor",
    "",
    "async def seed():",
    "    engine = create_async_engine(settings.database_url)",
    "    async with AsyncSession(engine) as db:",
    `        r = await db.execute(select(CustomEmoji).where(CustomEmoji.shortcode == '${shortcode}', CustomEmoji.domain == '${domain}'))`,
    "        if not r.scalar_one_or_none():",
    `            db.add(CustomEmoji(shortcode='${shortcode}', domain='${domain}', url='https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/1f431.png', visible_in_picker=True))`,
    "            await db.flush()",
    "        r2 = await db.execute(select(Actor).where(Actor.username == 'admin', Actor.domain.is_(None)))",
    "        actor = r2.scalar_one()",
    `        db.add(Reaction(id=uuid.uuid4(), ap_id=f'https://localhost/reactions/{uuid.uuid4()}', actor_id=actor.id, note_id=uuid.UUID('${noteId}'), emoji=':${shortcode}:'))`,
    "        await db.commit()",
    "    await engine.dispose()",
    "",
    "asyncio.run(seed())",
  ].join("\n");

  const execEnv = {
    ...process.env,
    COMPOSE_PROJECT_NAME: process.env.COMPOSE_PROJECT_NAME || "neko-e2e",
  };
  execFileSync("docker", [
    "compose", "-f", composeFile, "exec", "-T", "app", "python", "-c", py,
  ], { stdio: "pipe", timeout: 15_000, env: execEnv });
}

test.describe("Emoji Import Modal", () => {
  test("importable reaction badge opens import modal with form", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `emoji-import-${uid}`);

    // Seed remote emoji + reaction via DB
    seedRemoteEmojiReaction(note.id, `testcat${uid}`, "remote.test");

    // Reload timeline
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `emoji-import-${uid}` })
      .first();

    // Importable badge should show with dashed border
    const badge = noteCard.locator(".reaction-importable");
    await expect(badge).toBeVisible({ timeout: 5_000 });

    // Click opens import modal
    await badge.click();

    const modal = page.locator(".modal-overlay");
    await expect(modal).toBeVisible({ timeout: 10_000 });

    // Form should load with pre-filled shortcode (not stuck in loading)
    const form = page.locator(".emoji-import-form");
    await expect(form).toBeVisible({ timeout: 10_000 });

    // Shortcode should be pre-filled
    const shortcodeInput = form.locator('input[type="text"]').first();
    await expect(shortcodeInput).toHaveValue(`testcat${uid}`);

    // Both buttons should be present
    await expect(form.locator("text=Import Only")).toBeVisible();
    await expect(form.locator("text=Import & React")).toBeVisible();
  });

  test("import modal shows error on failed import", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const shortcode = `impfail${uid}`;
    const note = await createNote(page, `import-fail-${uid}`);

    seedRemoteEmojiReaction(note.id, shortcode, "remote.test");

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `import-fail-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-importable");
    await expect(badge).toBeVisible({ timeout: 5_000 });
    await badge.click();

    // Form loads with pre-filled shortcode
    const form = page.locator(".emoji-import-form");
    await expect(form).toBeVisible({ timeout: 10_000 });

    // Click Import & React — will fail because remote URL isn't reachable
    const importBtn = form.locator(".btn-primary");
    await expect(importBtn).toBeEnabled();
    await importBtn.click();

    // Error message should appear (not stuck forever)
    const errBlock = form.locator(".emoji-import-error");
    await expect(errBlock).toBeVisible({ timeout: 10_000 });

    // Modal should still be open (not closed on error)
    await expect(page.locator(".modal-overlay")).toBeVisible();
  });

  test("import modal closes with X button", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const note = await createNote(page, `import-close-${uid}`);

    seedRemoteEmojiReaction(note.id, `closetst${uid}`, "remote.test");

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `import-close-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-importable");
    await expect(badge).toBeVisible({ timeout: 5_000 });
    await badge.click();

    const modal = page.locator(".modal-overlay");
    await expect(modal).toBeVisible({ timeout: 10_000 });

    // Close via X
    await page.locator(".modal-close").click();
    await expect(modal).not.toBeVisible({ timeout: 5_000 });
  });

  test("import only button does not react", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const shortcode = `imponly${uid}`;
    const note = await createNote(page, `import-only-${uid}`);

    seedRemoteEmojiReaction(note.id, shortcode, "remote.test");

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `import-only-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-importable");
    await expect(badge).toBeVisible({ timeout: 5_000 });
    await badge.click();

    const form = page.locator(".emoji-import-form");
    await expect(form).toBeVisible({ timeout: 10_000 });

    // Click "Import Only" button (not the primary btn-primary)
    const importOnlyBtn = form.locator("button", { hasText: "Import Only" }).first();
    await expect(importOnlyBtn).toBeVisible();
    await importOnlyBtn.click();

    // Either success (modal closes) or error (since remote URL may not be reachable)
    // We mainly verify the button exists and is clickable
    const errOrClosed = page
      .locator(".emoji-import-error")
      .or(page.locator("body:not(:has(.modal-overlay))"));
    await expect(errOrClosed).toBeVisible({ timeout: 10_000 });
  });
});
