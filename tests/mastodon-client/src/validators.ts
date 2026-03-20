import { expect } from "vitest";

/** ISO 8601 with milliseconds and Z suffix: 2026-03-16T12:00:00.000Z */
const ISO_DATETIME_Z = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/;

export function assertDateTimeZ(value: unknown, field: string) {
  expect(value, `${field} should be a string`).toBeTypeOf("string");
  expect(value, `${field} should match ISO 8601 with Z suffix, got: ${value}`).toMatch(
    ISO_DATETIME_Z,
  );
}

export function assertAccount(account: any, label = "account") {
  expect(account, `${label} should not be null`).not.toBeNull();
  expect(account.id, `${label}.id`).toBeTypeOf("string");
  expect(account.username, `${label}.username`).toBeTypeOf("string");
  expect(account.acct, `${label}.acct`).toBeTypeOf("string");
  expect(account.display_name, `${label}.display_name should be string, not null`).toBeTypeOf(
    "string",
  );
  expect(account.note, `${label}.note`).toBeTypeOf("string");
  expect(account.url, `${label}.url`).toBeTypeOf("string");
  expect(account.avatar, `${label}.avatar`).toBeTypeOf("string");
  expect(account.avatar_static, `${label}.avatar_static`).toBeTypeOf("string");
  expect(account.header, `${label}.header should be string, not null`).toBeTypeOf("string");
  expect(account.header_static, `${label}.header_static`).toBeTypeOf("string");
  assertDateTimeZ(account.created_at, `${label}.created_at`);
  expect(account.bot, `${label}.bot`).toBeTypeOf("boolean");
  expect(account.group, `${label}.group`).toBeTypeOf("boolean");
  expect(account.locked, `${label}.locked`).toBeTypeOf("boolean");
  expect(account.followers_count, `${label}.followers_count`).toBeTypeOf("number");
  expect(account.following_count, `${label}.following_count`).toBeTypeOf("number");
  expect(account.statuses_count, `${label}.statuses_count`).toBeTypeOf("number");
  expect(Array.isArray(account.emojis), `${label}.emojis should be array`).toBe(true);
  expect(Array.isArray(account.fields), `${label}.fields should be array`).toBe(true);
}

export function assertStatus(status: any, label = "status") {
  expect(status, `${label} should not be null`).not.toBeNull();
  expect(status.id, `${label}.id`).toBeTypeOf("string");
  expect(status.uri, `${label}.uri`).toBeTypeOf("string");
  expect(status.url, `${label}.url`).toBeTypeOf("string");
  assertDateTimeZ(status.created_at, `${label}.created_at`);
  expect(status.content, `${label}.content`).toBeTypeOf("string");
  expect(
    ["public", "unlisted", "private", "direct"],
    `${label}.visibility should be valid`,
  ).toContain(status.visibility);
  expect(status.sensitive, `${label}.sensitive`).toBeTypeOf("boolean");
  expect(status.spoiler_text, `${label}.spoiler_text should be string, not null`).toBeTypeOf(
    "string",
  );
  expect(status.reblogs_count, `${label}.reblogs_count`).toBeTypeOf("number");
  expect(status.favourites_count, `${label}.favourites_count`).toBeTypeOf("number");
  expect(status.replies_count, `${label}.replies_count`).toBeTypeOf("number");
  expect(status.favourited, `${label}.favourited`).toBeTypeOf("boolean");
  expect(status.reblogged, `${label}.reblogged`).toBeTypeOf("boolean");
  expect(status.muted, `${label}.muted`).toBeTypeOf("boolean");
  expect(status.bookmarked, `${label}.bookmarked`).toBeTypeOf("boolean");
  expect(Array.isArray(status.mentions), `${label}.mentions should be array`).toBe(true);
  expect(Array.isArray(status.tags), `${label}.tags should be array`).toBe(true);
  expect(Array.isArray(status.emojis), `${label}.emojis should be array`).toBe(true);
  expect(Array.isArray(status.media_attachments), `${label}.media_attachments should be array`).toBe(true);
  expect(Array.isArray(status.filtered), `${label}.filtered should be array`).toBe(true);
  assertAccount(status.account, `${label}.account`);
}

export function assertNotification(notif: any, label = "notification") {
  expect(notif.id, `${label}.id`).toBeTypeOf("string");
  expect(notif.type, `${label}.type`).toBeTypeOf("string");
  assertDateTimeZ(notif.created_at, `${label}.created_at`);
  expect(notif.group_key, `${label}.group_key should be string`).toBeTypeOf("string");
  if (notif.account) {
    assertAccount(notif.account, `${label}.account`);
  }
  if (notif.status) {
    assertStatus(notif.status, `${label}.status`);
  }
}
