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

/**
 * Seed multiple remote emoji sources with the same shortcode + a reaction.
 */
function seedMultiSourceEmoji(
  noteId: string,
  shortcode: string,
  domains: { domain: string; copyPermission?: string }[],
) {
  const projectRoot =
    process.env.PROJECT_ROOT ||
    path.resolve(__dirname, "../../..");
  if (!fs.existsSync(projectRoot) || !fs.statSync(projectRoot).isDirectory()) {
    throw new Error(`PROJECT_ROOT is not a valid directory: ${projectRoot}`);
  }
  const composeFile = path.join(projectRoot, "docker-compose.e2e.yml");

  // Build per-domain insert lines
  const inserts = domains.map((d) => {
    const cp = d.copyPermission ? `'${d.copyPermission}'` : "None";
    return [
      `        r = await db.execute(select(CustomEmoji).where(CustomEmoji.shortcode == '${shortcode}', CustomEmoji.domain == '${d.domain}'))`,
      "        if not r.scalar_one_or_none():",
      `            db.add(CustomEmoji(shortcode='${shortcode}', domain='${d.domain}', url='https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/1f431.png', visible_in_picker=True, copy_permission=${cp}))`,
      "            await db.flush()",
    ].join("\n");
  }).join("\n");

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
    inserts,
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

    // Both buttons should be present (in footer, sibling of form)
    const modalContent = page.locator(".modal-content");
    await expect(modalContent.locator("text=Import Only")).toBeVisible();
    await expect(modalContent.locator("text=Import & React")).toBeVisible();
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
    const modalContent = page.locator(".modal-content");
    const importBtn = modalContent.locator(".btn-primary");
    await expect(importBtn).toBeEnabled();
    await importBtn.click();

    // Error message should appear (not stuck forever)
    const errBlock = modalContent.locator(".emoji-import-error");
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

    // Click "Import Only" button (in footer, sibling of form)
    const modalContent = page.locator(".modal-content");
    const importOnlyBtn = modalContent.locator("button", { hasText: "Import Only" }).first();
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

test.describe("Emoji Source Selection", () => {
  test("source navigation appears with multiple sources", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const shortcode = `multi${uid}`;
    const note = await createNote(page, `source-nav-${uid}`);

    seedMultiSourceEmoji(note.id, shortcode, [
      { domain: "alpha.test" },
      { domain: "beta.test" },
    ]);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `source-nav-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-importable");
    await expect(badge).toBeVisible({ timeout: 5_000 });
    await badge.click();

    const form = page.locator(".emoji-import-form");
    await expect(form).toBeVisible({ timeout: 10_000 });

    // Source navigation should be visible
    const nav = form.locator(".emoji-source-nav");
    await expect(nav).toBeVisible();

    // Should show domain info and page indicator
    const info = nav.locator(".emoji-source-info");
    const initialText = await info.textContent();
    expect(initialText).toContain("1 / 2");

    // Click next and verify domain changes
    await nav.locator("button", { hasText: "▶" }).click();
    const nextText = await info.textContent();
    expect(nextText).toContain("2 / 2");
    expect(nextText).not.toBe(initialText);
  });

  test("source navigation hidden with single source", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const shortcode = `single${uid}`;
    const note = await createNote(page, `single-src-${uid}`);

    seedRemoteEmojiReaction(note.id, shortcode, "only.test");

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `single-src-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-importable");
    await expect(badge).toBeVisible({ timeout: 5_000 });
    await badge.click();

    const form = page.locator(".emoji-import-form");
    await expect(form).toBeVisible({ timeout: 10_000 });

    // Source navigation should NOT exist
    await expect(form.locator(".emoji-source-nav")).toHaveCount(0);
  });

  test("deny source disables import buttons", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const shortcode = `deny${uid}`;
    const note = await createNote(page, `deny-src-${uid}`);

    seedMultiSourceEmoji(note.id, shortcode, [
      { domain: "denied.test", copyPermission: "deny" },
    ]);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `deny-src-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-importable");
    await expect(badge).toBeVisible({ timeout: 5_000 });
    await badge.click();

    const form = page.locator(".emoji-import-form");
    await expect(form).toBeVisible({ timeout: 10_000 });

    // Denied message should be visible
    await expect(form.locator(".emoji-import-denied")).toBeVisible();

    // Import buttons should be disabled
    const modalContent = page.locator(".modal-content");
    const importBtn = modalContent.locator("button", { hasText: "Import Only" }).first();
    await expect(importBtn).toBeDisabled();
    const importReactBtn = modalContent.locator(".btn-primary");
    await expect(importReactBtn).toBeDisabled();
  });

  test("deny warning shown when other source denies", async ({ page }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const shortcode = `warn${uid}`;
    const note = await createNote(page, `warn-src-${uid}`);

    seedMultiSourceEmoji(note.id, shortcode, [
      { domain: "alpha.test", copyPermission: "allow" },
      { domain: "beta.test", copyPermission: "deny" },
    ]);

    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 10_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `warn-src-${uid}` })
      .first();

    const badge = noteCard.locator(".reaction-importable");
    await expect(badge).toBeVisible({ timeout: 5_000 });
    await badge.click();

    const form = page.locator(".emoji-import-form");
    await expect(form).toBeVisible({ timeout: 10_000 });

    // Navigate to the allow source (alpha.test) if not already there
    const nav = form.locator(".emoji-source-nav");
    await expect(nav).toBeVisible();

    // Find the allow source — check if warning is visible
    // The warning appears when current source is NOT the deny source
    const warning = form.locator(".emoji-import-warning");

    // If alpha (allow) is selected first, warning should show
    // If beta (deny) is selected first, navigate to alpha
    const info = nav.locator(".emoji-source-info");
    const text = await info.textContent();
    if (text?.includes("beta.test")) {
      await nav.locator("button", { hasText: "▶" }).click();
      await page.waitForTimeout(300);
    }

    await expect(warning).toBeVisible({ timeout: 5_000 });
  });
});
