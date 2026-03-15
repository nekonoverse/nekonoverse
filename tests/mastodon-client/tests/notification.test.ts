import { describe, it, expect, beforeAll } from "vitest";
import { getAccessToken, createAuthenticatedClient, waitForHealth, authedFetch, createStatus } from "../src/setup";
import { assertNotification } from "../src/validators";
import type { mastodon } from "masto";

describe("Notification API", () => {
  let tokenA: string;
  let tokenB: string;
  let clientB: mastodon.rest.Client;

  beforeAll(async () => {
    await waitForHealth();
    ({ token: tokenA } = await getAccessToken("notifuser1", "testpassword123"));
    ({ token: tokenB } = await getAccessToken("notifuser2", "testpassword123"));
    // Use masto.js client for actions (favourite, follow) since they're easier
    clientB = (await import("masto")).createRestAPIClient({
      url: process.env.TEST_SERVER_URL || "http://localhost:3080",
      accessToken: tokenB,
    });
  });

  it("favourite creates a notification with valid fields", async () => {
    // User A creates a post
    const status = await createStatus(tokenA, {
      status: "Favourite me!",
      visibility: "public",
    });

    // User B favourites it
    await clientB.v1.statuses.$select(status.id).favourite();

    // Allow a moment for async processing
    await new Promise((r) => setTimeout(r, 1000));

    // User A should have a notification (raw JSON)
    const notifications = await authedFetch("/api/v1/notifications", tokenA);
    const raw = notifications.find(
      (n: any) => n.type === "favourite" && n.status?.id === status.id,
    );
    expect(raw, "favourite notification should exist").toBeDefined();
    assertNotification(raw, "favourite notification");
    expect(raw.type).toBe("favourite");
  });

  it("follow creates a notification with valid fields", async () => {
    // Get user A's account ID
    const meA = await authedFetch("/api/v1/accounts/verify_credentials", tokenA);

    // User B follows user A
    await clientB.v1.accounts.$select(meA.id).follow();

    await new Promise((r) => setTimeout(r, 1000));

    const notifications = await authedFetch("/api/v1/notifications", tokenA);
    const raw = notifications.find((n: any) => n.type === "follow");
    expect(raw, "follow notification should exist").toBeDefined();
    assertNotification(raw, "follow notification");
    expect(raw.type).toBe("follow");
  });

  it("mention creates a notification with status", async () => {
    const meA = await authedFetch("/api/v1/accounts/verify_credentials", tokenA);

    // User B mentions user A
    await createStatus(tokenB, {
      status: `@${meA.username} hello!`,
      visibility: "public",
    });

    await new Promise((r) => setTimeout(r, 1000));

    const notifications = await authedFetch("/api/v1/notifications", tokenA);
    const raw = notifications.find((n: any) => n.type === "mention");
    expect(raw, "mention notification should exist").toBeDefined();
    assertNotification(raw, "mention notification");
    expect(raw.status).toBeDefined();
  });
});
