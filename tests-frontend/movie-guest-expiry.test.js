"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { GUEST_PROJECT_TTL_MS, normalizeGuestProjectExpiry } = require("../movie-guest-expiry.js");

test("valid guest expiry is preserved without extending its lifetime", () => {
  const project = { id: "guest-1", guestExpiresAt: "2026-11-25T12:00:00.000Z" };
  const result = normalizeGuestProjectExpiry(project, Date.parse("2026-11-24T12:00:00.000Z"));
  assert.equal(result.changed, false);
  assert.equal(result.project, project);
  assert.equal(result.project.guestExpiresAt, "2026-11-25T12:00:00.000Z");
});

test("missing or malformed guest expiry receives a safe 24-hour deadline", () => {
  const now = Date.parse("2026-11-24T12:00:00.000Z");
  for (const guestExpiresAt of [undefined, "", "not-a-date"]) {
    const result = normalizeGuestProjectExpiry({ id: "guest-1", guestExpiresAt }, now);
    assert.equal(result.changed, true);
    assert.equal(Date.parse(result.project.guestExpiresAt), now + GUEST_PROJECT_TTL_MS);
    assert.equal(result.project.id, "guest-1");
  }
});

test("normalization does not mutate the original project", () => {
  const original = { id: "guest-2" };
  const result = normalizeGuestProjectExpiry(original, 0);
  assert.equal(original.guestExpiresAt, undefined);
  assert.notEqual(result.project, original);
});
