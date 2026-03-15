import { describe, it, expect, beforeAll } from "vitest";
import { BASE_URL, waitForHealth } from "../src/setup";

describe("Instance API", () => {
  beforeAll(async () => {
    await waitForHealth();
  });

  it("GET /api/v1/instance returns required fields", async () => {
    const resp = await fetch(`${BASE_URL}/api/v1/instance`);
    expect(resp.ok).toBe(true);
    const data = await resp.json();

    expect(data.uri).toBeTypeOf("string");
    expect(data.title).toBeTypeOf("string");
    expect(data.description).toBeTypeOf("string");
    expect(data.version).toBeTypeOf("string");
    expect(typeof data.registrations).toBe("boolean");
    expect(typeof data.approval_required).toBe("boolean");
    expect(Array.isArray(data.languages)).toBe(true);
    expect(Array.isArray(data.rules)).toBe(true);

    // stats
    expect(data.stats).toBeDefined();
    expect(data.stats.user_count).toBeTypeOf("number");
    expect(data.stats.status_count).toBeTypeOf("number");
    expect(data.stats.domain_count).toBeTypeOf("number");

    // configuration
    expect(data.configuration).toBeDefined();
    expect(data.configuration.statuses).toBeDefined();
    expect(data.configuration.statuses.max_characters).toBeTypeOf("number");
    expect(data.configuration.media_attachments).toBeDefined();
    expect(data.configuration.polls).toBeDefined();

    // thumbnail should be string or absent (not object)
    if (data.thumbnail !== undefined && data.thumbnail !== null) {
      expect(data.thumbnail).toBeTypeOf("string");
    }

    // contact
    expect(data.contact).toBeDefined();
    expect(data.contact.email).toBeTypeOf("string");
  });
});
