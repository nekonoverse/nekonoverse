import { describe, it, expect, beforeAll } from "vitest";
import { getAccessToken, waitForHealth, authedFetch, createStatus } from "../src/setup";
import { assertStatus, assertDateTimeZ } from "../src/validators";

describe("Status API", () => {
  let token: string;

  beforeAll(async () => {
    await waitForHealth();
    ({ token } = await getAccessToken("statustest", "testpassword123"));
  });

  it("created status has all required fields", async () => {
    const raw = await createStatus(token, {
      status: "Hello from masto.js test!",
      visibility: "public",
    });
    assertStatus(raw);
  });

  it("spoiler_text is empty string, not null", async () => {
    const raw = await createStatus(token, {
      status: "No spoiler",
      visibility: "public",
    });
    expect(raw.spoiler_text).toBe("");
  });

  it("status with spoiler_text returns it", async () => {
    const raw = await createStatus(token, {
      status: "Content warning test",
      visibility: "public",
      spoiler_text: "CW",
    });
    expect(raw.spoiler_text).toBe("CW");
  });

  it("get status by ID returns valid status", async () => {
    const created = await createStatus(token, {
      status: "Fetch me",
      visibility: "public",
    });
    const fetched = await authedFetch(`/api/v1/statuses/${created.id}`, token);
    assertStatus(fetched);
  });

  it("reply has in_reply_to_id", async () => {
    const parent = await createStatus(token, {
      status: "Parent post",
      visibility: "public",
    });
    const reply = await createStatus(token, {
      status: "Reply post",
      visibility: "public",
      in_reply_to_id: parent.id,
    });
    assertStatus(reply);
    expect(reply.in_reply_to_id).toBe(parent.id);
    expect(reply.in_reply_to_account_id).toBeTypeOf("string");
  });

  it("context returns ancestors and descendants", async () => {
    const parent = await createStatus(token, {
      status: "Context parent",
      visibility: "public",
    });
    await createStatus(token, {
      status: "Context reply",
      visibility: "public",
      in_reply_to_id: parent.id,
    });
    const context = await authedFetch(`/api/v1/statuses/${parent.id}/context`, token);
    expect(Array.isArray(context.ancestors)).toBe(true);
    expect(Array.isArray(context.descendants)).toBe(true);
    if (context.descendants.length > 0) {
      assertStatus(context.descendants[0], "context.descendant");
    }
  });
});
