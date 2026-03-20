/**
 * Reaction stress test — validates correctness and performance of
 * custom emoji reaction grouping under load.
 *
 * NOT included in CI. Run manually:
 *   STRESS_TEST=1 npx playwright test reaction-stress
 */
import { test, expect } from "@playwright/test";
import {
  loginAsAdmin,
  createNote,
  registerAndLogin,
  pngOfSize,
} from "./helpers";
import { execSync } from "child_process";
import * as path from "path";

// Skip unless STRESS_TEST env is set
test.skip(!process.env.STRESS_TEST, "Stress test: set STRESS_TEST=1 to run");

/**
 * Seed a remote custom emoji record and a reaction from a specific actor.
 */
function seedRemoteReaction(
  noteId: string,
  shortcode: string,
  domain: string,
  actorUsername: string,
) {
  const projectRoot =
    process.env.PROJECT_ROOT || path.resolve(__dirname, "../../..");
  const composeArgs = ["-f", `${projectRoot}/docker-compose.e2e.yml`];

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
    `        r2 = await db.execute(select(Actor).where(Actor.username == '${actorUsername}', Actor.domain.is_(None)))`,
    "        actor = r2.scalar_one()",
    `        db.add(Reaction(id=uuid.uuid4(), ap_id=f'https://localhost/reactions/{uuid.uuid4()}', actor_id=actor.id, note_id=uuid.UUID('${noteId}'), emoji=':${shortcode}@${domain}:'))`,
    "        await db.commit()",
    "    await engine.dispose()",
    "",
    "asyncio.run(seed())",
  ].join("\n");

  const cmd = `docker compose ${composeArgs.join(" ")} exec -T app python -c '${py.replace(/'/g, "'\"'\"'")}'`;
  try {
    execSync(cmd, { stdio: "pipe", timeout: 15_000 });
  } catch {
    const fallback = `docker compose exec -T app python -c '${py.replace(/'/g, "'\"'\"'")}'`;
    execSync(fallback, { stdio: "pipe", timeout: 15_000 });
  }
}

test.describe("Reaction stress test", () => {
  test.setTimeout(120_000);

  test("many custom emoji reactions render and group correctly", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3080";

    // Step 1: Create 10 custom emoji with distinct images
    const emojiShortcodes: string[] = [];
    for (let i = 0; i < 10; i++) {
      const shortcode = `stress${uid}_${i}`;
      emojiShortcodes.push(shortcode);
      const png = pngOfSize(32 + i, 32 + i); // distinct size → distinct image
      const resp = await page.request.post("/api/v1/admin/emoji/add", {
        multipart: {
          file: {
            name: `${shortcode}.png`,
            mimeType: "image/png",
            buffer: png,
          },
          shortcode,
        },
      });
      expect(resp.ok()).toBeTruthy();
    }

    // Step 2: Create a note
    const note = await createNote(page, `stress-test-${uid}`);

    // Step 3: Register 5 users, each reacts with 2 different custom emoji
    const users: { page: any; context: any }[] = [];
    for (let u = 0; u < 5; u++) {
      const { page: p, context: c } = await registerAndLogin(
        browser,
        `stressuser${uid}_${u}`,
        "StressPass1!",
        baseURL,
      );
      for (let e = 0; e < 2; e++) {
        const emojiIdx = (u * 2 + e) % emojiShortcodes.length;
        const encodedEmoji = encodeURIComponent(
          `:${emojiShortcodes[emojiIdx]}:`,
        );
        const resp = await p.request.post(
          `/api/v1/statuses/${note.id}/react/${encodedEmoji}`,
        );
        expect(resp.ok()).toBeTruthy();
      }
      users.push({ page: p, context: c });
    }
    for (const { context } of users) {
      await context.close();
    }

    // Step 4: Load timeline and verify all reaction badges render
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 15_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `stress-test-${uid}` })
      .first();

    const badges = noteCard.locator(".reaction-badge");
    await expect(badges.first()).toBeVisible({ timeout: 15_000 });

    const badgeCount = await badges.count();
    expect(badgeCount).toBeGreaterThan(0);
    expect(badgeCount).toBeLessThanOrEqual(10);

    // Verify total count sums to 10 (5 users × 2 reactions each)
    let totalCount = 0;
    for (let i = 0; i < badgeCount; i++) {
      const text = await badges.nth(i).textContent();
      const num = parseInt(text?.replace(/\D/g, "") || "0", 10);
      totalCount += num;
    }
    expect(totalCount).toBe(10);
  });

  test("same shortcode from local and remote groups into one badge", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3080";
    const shortcode = `samesc${uid}`;

    // Create local custom emoji
    const png = pngOfSize(32, 32);
    const addResp = await page.request.post("/api/v1/admin/emoji/add", {
      multipart: {
        file: {
          name: `${shortcode}.png`,
          mimeType: "image/png",
          buffer: png,
        },
        shortcode,
      },
    });
    expect(addResp.ok()).toBeTruthy();

    const note = await createNote(page, `samesc-test-${uid}`);

    // User 1: react with local emoji
    const { page: p1, context: c1 } = await registerAndLogin(
      browser,
      `scuser1_${uid}`,
      "Pass1234!",
      baseURL,
    );
    const resp1 = await p1.request.post(
      `/api/v1/statuses/${note.id}/react/${encodeURIComponent(`:${shortcode}:`)}`,
    );
    expect(resp1.ok()).toBeTruthy();
    await c1.close();

    // Seed a remote reaction with same shortcode but different domain (via DB)
    seedRemoteReaction(note.id, shortcode, "remote.test", "admin");

    // Load timeline → should see ONE badge with count 2
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 15_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `samesc-test-${uid}` })
      .first();

    const badges = noteCard.locator(".reaction-badge");
    await expect(badges.first()).toBeVisible({ timeout: 10_000 });
    await expect(badges).toHaveCount(1, { timeout: 5_000 });
    await expect(badges.first()).toContainText("2");
  });

  test("concurrent reactions from multiple users arrive correctly", async ({
    page,
    browser,
  }) => {
    await loginAsAdmin(page);
    const uid = Date.now();
    const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3080";

    // Create 3 custom emoji
    for (let i = 0; i < 3; i++) {
      const sc = `conc${uid}_${i}`;
      const resp = await page.request.post("/api/v1/admin/emoji/add", {
        multipart: {
          file: {
            name: `${sc}.png`,
            mimeType: "image/png",
            buffer: pngOfSize(24 + i * 4, 24 + i * 4),
          },
          shortcode: sc,
        },
      });
      expect(resp.ok()).toBeTruthy();
    }

    const note = await createNote(page, `concurrent-test-${uid}`);

    // Load timeline first to establish SSE connection
    await page.goto("/");
    await page.waitForSelector(".note-card", { timeout: 15_000 });

    const noteCard = page
      .locator(".note-card")
      .filter({ hasText: `concurrent-test-${uid}` })
      .first();

    // Fire 3 reactions concurrently from different users
    const reactPromises = [];
    for (let i = 0; i < 3; i++) {
      reactPromises.push(
        (async () => {
          const { page: p, context: c } = await registerAndLogin(
            browser,
            `concuser${uid}_${i}`,
            "ConcPass1!",
            baseURL,
          );
          const emoji = encodeURIComponent(`:conc${uid}_${i}:`);
          const resp = await p.request.post(
            `/api/v1/statuses/${note.id}/react/${emoji}`,
          );
          expect(resp.ok()).toBeTruthy();
          await c.close();
        })(),
      );
    }
    await Promise.all(reactPromises);

    // Wait for SSE to deliver all 3 reactions
    const badges = noteCard.locator(".reaction-badge");
    await expect(badges).toHaveCount(3, { timeout: 15_000 });

    // All should show count 1
    for (let i = 0; i < 3; i++) {
      await expect(badges.nth(i)).toContainText("1");
    }
  });
});
