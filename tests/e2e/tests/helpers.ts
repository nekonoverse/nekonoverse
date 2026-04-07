import { type Page, type APIRequestContext, expect } from "@playwright/test";

/**
 * Log in as the pre-created admin user via the login form.
 * Navigates to /login, fills the form, submits, and waits for the
 * verify_credentials API call to confirm the session is established.
 */
export async function loginAsAdmin(page: Page) {
  await page.addInitScript(() =>
    localStorage.setItem("nekonoverse:input-mode", "auto"),
  );
  await page.goto("/login");
  await page.waitForSelector("#username", { timeout: 15_000 });
  await page.fill("#username", "admin");
  await page.fill("#password", "testpassword123");

  const credentialsPromise = page.waitForResponse(
    (r) => r.url().includes("/verify_credentials") && r.status() === 200,
    { timeout: 15_000 },
  );
  await page.click('button[type="submit"]');
  await credentialsPromise;
  await page.waitForURL("/", { timeout: 10_000 });
}

/**
 * Tab text to URL section mapping for the admin card menu.
 */
const adminSectionMap: Record<string, string> = {
  Overview: "",
  "Server Settings": "settings",
  Users: "users",
  "Domain Blocks": "domains",
  Federation: "federation",
  Reports: "reports",
  "Moderation Log": "log",
  Emoji: "emoji",
  Files: "files",
  Invitations: "invites",
};

/**
 * Navigate to an admin sub-page by section name.
 * Uses URL-based routing (card menu pattern).
 */
export async function goToAdminTab(page: Page, tabText: string) {
  const section = adminSectionMap[tabText] ?? tabText.toLowerCase();
  const path = section ? `/admin/${section}` : "/admin";
  await page.goto(path);
  // Wait for admin page to render (breadcrumb for sub-pages, menu for landing)
  if (section) {
    await page.waitForSelector(".breadcrumb", { timeout: 15_000 });
  } else {
    await page.waitForSelector(".settings-menu", { timeout: 15_000 });
  }
}

/**
 * Generate a minimal 1x1 PNG as a Buffer for file upload tests.
 */
export function png1x1(): Buffer {
  return Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/58BAwAI/AL+hc2rNAAAAABJRU5ErkJggg==",
    "base64",
  );
}

/**
 * Generate a valid PNG of arbitrary dimensions filled with a single color.
 * Uses raw zlib deflate to create a minimal but valid PNG.
 */
export function pngOfSize(width: number, height: number): Buffer {
  const { deflateSync } = require("zlib");

  // PNG signature
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);

  // IHDR chunk
  const ihdrData = Buffer.alloc(13);
  ihdrData.writeUInt32BE(width, 0);
  ihdrData.writeUInt32BE(height, 4);
  ihdrData[8] = 8; // bit depth
  ihdrData[9] = 2; // color type (RGB)
  ihdrData[10] = 0; // compression
  ihdrData[11] = 0; // filter
  ihdrData[12] = 0; // interlace
  const ihdr = makeChunk("IHDR", ihdrData);

  // IDAT chunk — each row: filter byte (0) + RGB pixels
  const rowSize = 1 + width * 3;
  const raw = Buffer.alloc(rowSize * height);
  for (let y = 0; y < height; y++) {
    raw[y * rowSize] = 0; // no filter
    for (let x = 0; x < width; x++) {
      const offset = y * rowSize + 1 + x * 3;
      // Simple color pattern based on position
      raw[offset] = (x * 37 + y * 59) & 0xff;
      raw[offset + 1] = (x * 73 + y * 97) & 0xff;
      raw[offset + 2] = (x * 113 + y * 131) & 0xff;
    }
  }
  const compressed = deflateSync(raw);
  const idat = makeChunk("IDAT", compressed);

  // IEND chunk
  const iend = makeChunk("IEND", Buffer.alloc(0));

  return Buffer.concat([signature, ihdr, idat, iend]);
}

function makeChunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeBuffer = Buffer.from(type, "ascii");
  const crcInput = Buffer.concat([typeBuffer, data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(crcInput), 0);
  return Buffer.concat([length, typeBuffer, data, crc]);
}

function crc32(buf: Buffer): number {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) {
    c = c ^ buf[i];
    for (let j = 0; j < 8; j++) {
      c = (c >>> 1) ^ (c & 1 ? 0xedb88320 : 0);
    }
  }
  return (c ^ 0xffffffff) >>> 0;
}

/**
 * Create a note via the API. Requires an authenticated page (call loginAsAdmin first).
 * Returns the created note's JSON response.
 */
export async function createNote(page: Page, text: string, visibility = "public") {
  const resp = await page.request.post("/api/v1/statuses", {
    data: { content: text, visibility },
  });
  expect(resp.status()).toBe(201);
  return resp.json();
}

/**
 * Register a new user via the API.
 * Returns the created user's JSON response.
 */
export async function registerUser(
  page: Page,
  username: string,
  password: string,
) {
  // レートリミット(429)対策: リトライ付き
  for (let attempt = 0; attempt < 5; attempt++) {
    const resp = await page.request.post("/api/v1/accounts", {
      data: {
        username,
        email: `${username}@test.example.com`,
        password,
      },
    });
    if (resp.status() === 429) {
      await new Promise((r) => setTimeout(r, 1000 * (attempt + 1)));
      continue;
    }
    expect(resp.status()).toBe(201);
    return resp.json();
  }
  throw new Error(
    `registerUser: rate limited after 5 attempts for ${username}`,
  );
}

/**
 * Log in as any user via the login form.
 * Navigates to /login, fills the form, submits, and waits for
 * verify_credentials to confirm the session is established.
 */
export async function loginAsUser(
  page: Page,
  username: string,
  password: string,
) {
  await page.addInitScript(() =>
    localStorage.setItem("nekonoverse:input-mode", "auto"),
  );
  await page.goto("/login");
  await page.waitForSelector("#username", { timeout: 15_000 });
  await page.fill("#username", username);
  await page.fill("#password", password);

  const credentialsPromise = page.waitForResponse(
    (resp) =>
      resp.url().includes("/verify_credentials") && resp.status() === 200,
    { timeout: 15_000 },
  );

  await page.click('button[type="submit"]');
  await credentialsPromise;
  await page.waitForURL("/", { timeout: 10_000 });
}

/**
 * Register a user and log in, returning the page ready for that user.
 * Uses a separate browser context to avoid polluting the caller's session.
 * Returns { page, context, user } for the newly created user.
 */
export async function registerAndLogin(
  browser: import("@playwright/test").Browser,
  username: string,
  password: string,
  baseURL: string,
) {
  const context = await browser.newContext({ baseURL });
  const page = await context.newPage();

  // registerUser を呼ぶとセッションクッキーが設定される
  const user = await registerUser(page, username, password);
  // ログインページを経由してSPAセッションを確立する
  await loginAsUser(page, username, password);
  return { page, context, user };
}

/**
 * Look up an account by username and return the actor_id.
 * verify_credentialsはuser.idを返すが、follow等のAPIはactor_idを要求するため
 * accounts/lookupを使ってactor_idを取得する。
 */
export async function getActorId(page: Page, username: string) {
  const resp = await page.request.get(
    `/api/v1/accounts/lookup?acct=${username}`,
  );
  expect(resp.ok()).toBeTruthy();
  const account = await resp.json();
  return account.id as string;
}
