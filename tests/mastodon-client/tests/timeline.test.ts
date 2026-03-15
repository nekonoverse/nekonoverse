import { describe, it, expect, beforeAll } from "vitest";
import { getAccessToken, waitForHealth, authedFetch, createStatus, BASE_URL } from "../src/setup";
import { assertStatus } from "../src/validators";

describe("Timeline API", () => {
  let token: string;

  beforeAll(async () => {
    await waitForHealth();
    ({ token } = await getAccessToken("tltest", "testpassword123"));

    // Create a few public posts to populate the timeline
    for (let i = 0; i < 3; i++) {
      await createStatus(token, {
        status: `Timeline test post ${i}`,
        visibility: "public",
      });
    }
  });

  it("public timeline returns array of valid statuses", async () => {
    const resp = await fetch(`${BASE_URL}/api/v1/timelines/public`);
    expect(resp.ok).toBe(true);
    const data = await resp.json();
    expect(Array.isArray(data)).toBe(true);
    expect(data.length).toBeGreaterThan(0);

    for (const status of data.slice(0, 3)) {
      assertStatus(status, "public timeline status");
    }
  });

  it("home timeline returns array of valid statuses", async () => {
    const data = await authedFetch("/api/v1/timelines/home", token);
    expect(Array.isArray(data)).toBe(true);

    for (const status of data.slice(0, 3)) {
      assertStatus(status, "home timeline status");
    }
  });
});
