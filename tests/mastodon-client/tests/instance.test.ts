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

  it("GET /api/v2/instance returns v2 structure", async () => {
    const resp = await fetch(`${BASE_URL}/api/v2/instance`);
    expect(resp.ok).toBe(true);
    const data = await resp.json();

    // v2 uses "domain" instead of "uri"
    expect(data.domain).toBeTypeOf("string");
    expect(data.title).toBeTypeOf("string");
    expect(data.version).toBeTypeOf("string");
    expect(data.source_url).toBeTypeOf("string");
    expect(data.description).toBeTypeOf("string");
    expect(Array.isArray(data.languages)).toBe(true);
    expect(Array.isArray(data.rules)).toBe(true);
    expect(Array.isArray(data.icon)).toBe(true);

    // usage (v2 replaces stats)
    expect(data.usage).toBeDefined();
    expect(data.usage.users).toBeDefined();
    expect(data.usage.users.active_month).toBeTypeOf("number");

    // registrations is an object (not boolean like v1)
    expect(data.registrations).toBeDefined();
    expect(typeof data.registrations).toBe("object");
    expect(typeof data.registrations.enabled).toBe("boolean");
    expect(typeof data.registrations.approval_required).toBe("boolean");

    // configuration (expanded in v2)
    expect(data.configuration).toBeDefined();
    expect(data.configuration.urls).toBeDefined();
    expect(data.configuration.urls.streaming).toBeTypeOf("string");
    expect(data.configuration.statuses).toBeDefined();
    expect(data.configuration.statuses.max_characters).toBeTypeOf("number");
    expect(data.configuration.media_attachments).toBeDefined();
    expect(data.configuration.polls).toBeDefined();
    expect(data.configuration.accounts).toBeDefined();
    expect(data.configuration.translation).toBeDefined();
    expect(typeof data.configuration.translation.enabled).toBe("boolean");

    // api_versions
    expect(data.api_versions).toBeDefined();
    expect(data.api_versions.mastodon).toBeTypeOf("number");

    // contact (v2 has nested object)
    expect(data.contact).toBeDefined();
    expect(data.contact.email).toBeTypeOf("string");

    // thumbnail should be object or null (not string like v1)
    if (data.thumbnail !== null) {
      expect(typeof data.thumbnail).toBe("object");
      expect(data.thumbnail.url).toBeTypeOf("string");
    }
  });
});
